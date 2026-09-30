;;; talktype-test.el --- ERT tests for talktype.el -*- lexical-binding: t; -*-

;; emacs --batch -Q -L . -l tests/talktype-test.el -f ert-run-tests-batch-and-exit

;;; Code:

(require 'cl-lib)
(require 'ert)
(require 'talktype)

(defmacro talktype-test--in-buffer (content &rest body)
  "Run BODY with a fresh buffer holding CONTENT in the selected window.
Point is at the end of CONTENT."
  (declare (indent 1))
  `(let ((buffer (generate-new-buffer "*talktype-test*")))
     (unwind-protect
         (progn
           (set-window-buffer (selected-window) buffer)
           (with-current-buffer buffer
             (buffer-enable-undo)
             (insert ,content)
             (undo-boundary)
             ,@body))
       (talktype-end)
       (kill-buffer buffer))))

(defun talktype-test--undo-once ()
  "Undo one step in the current buffer, as one `undo' would."
  (undo-boundary)
  (let ((list buffer-undo-list))
    (when (null (car list))
      (setq list (cdr list)))
    (primitive-undo 1 list)))

(ert-deftest talktype-test-appends-at-point-and-keeps-text-on-end ()
  (talktype-test--in-buffer "Hallo "
    (talktype-begin)
    (talktype-append "Welt,")
    (talktype-append " wie geht's?")
    (should (equal (buffer-string) "Hallo Welt, wie geht's?"))
    (should (eq (get-char-property 7 'face) 'talktype-provisional))
    (talktype-end)
    (should (equal (buffer-string) "Hallo Welt, wie geht's?"))
    (should-not (get-char-property 7 'face))
    (should-not talktype--overlay)))

(ert-deftest talktype-test-inserts-special-characters-literally ()
  (let ((text " \"quoted\" back\\slash (progn (kill-emacs)) Grüße ß €\nzweite Zeile"))
    (talktype-test--in-buffer "x"
      (talktype-begin)
      (talktype-append text)
      (talktype-end)
      (should (equal (buffer-string) (concat "x" text))))))

(ert-deftest talktype-test-one-undo-removes-the-whole-dictation ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (dolist (words '(" eins" " zwei" " drei"))
      (talktype-append words)
      ;; Commands and undo timers put boundaries between the server calls.
      (undo-boundary))
    (talktype-replace-region " eins zwei drei.")
    (undo-boundary)
    (talktype-end)
    (should (equal (buffer-string) "Hallo eins zwei drei."))
    (talktype-test--undo-once)
    (should (equal (buffer-string) "Hallo"))))

;; Amalgamating would make the dictation's undo take the typed "!" along.
(ert-deftest talktype-test-undo-keeps-edits-typed-during-the-dictation ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (talktype-append " eins")
    (undo-boundary)
    (save-excursion
      (goto-char (point-min))
      (insert "!"))
    (undo-boundary)
    (talktype-append " zwei")
    (talktype-end)
    (should (equal (buffer-string) "!Hallo eins zwei"))
    (talktype-test--undo-once)
    (should (equal (buffer-string) "!Hallo eins"))))

(ert-deftest talktype-test-point-follows-only-from-the-region-end ()
  (talktype-test--in-buffer "Anfang Ende"
    (goto-char 7)
    (talktype-begin)
    (talktype-append " Mitte")
    (should (= (point) 13))
    (goto-char (point-min))
    (talktype-append " und mehr")
    (should (= (point) (point-min)))
    (talktype-end)
    (should (equal (buffer-string) "Anfang Mitte und mehr Ende"))))

(ert-deftest talktype-test-keeps-the-mark-active ()
  (talktype-test--in-buffer "markiert"
    (let ((transient-mark-mode t))
      (push-mark (point-min) t t)
      (setq deactivate-mark nil)
      (talktype-begin)
      (talktype-append " dazu")
      (should-not deactivate-mark)
      (should (region-active-p))
      (should (= (mark) (point-min))))))

(ert-deftest talktype-test-replace-region-replaces-only-the-dictation ()
  (talktype-test--in-buffer "Vorher "
    (talktype-begin)
    (talktype-append "falsch erkannt")
    (talktype-replace-region "richtig")
    (should (equal (buffer-string) "Vorher richtig"))
    (talktype-append " weiter")
    (talktype-end)
    (should (equal (buffer-string) "Vorher richtig weiter"))))

(ert-deftest talktype-test-text-typed-before-the-region-stays-outside ()
  (talktype-test--in-buffer "a"
    (talktype-begin)
    (talktype-append "diktiert")
    (save-excursion (goto-char 2) (insert "getippt "))
    (talktype-replace-region "neu")
    (talktype-end)
    (should (equal (buffer-string) "agetippt neu"))))

(ert-deftest talktype-test-refuses-read-only-buffers ()
  (talktype-test--in-buffer "nur lesen"
    (setq buffer-read-only t)
    (should-error (talktype-begin) :type 'user-error)
    (should-not talktype--overlay)))

(ert-deftest talktype-test-refuses-the-minibuffer ()
  (let ((minibuffer (window-buffer (minibuffer-window))))
    (with-current-buffer minibuffer
      (should-error (talktype--check-writable minibuffer) :type 'user-error))))

(ert-deftest talktype-test-stops-when-the-buffer-turns-read-only ()
  (talktype-test--in-buffer "Text"
    (talktype-begin)
    (talktype-append " eins")
    (setq buffer-read-only t)
    (should-error (talktype-append " zwei") :type 'user-error)
    (should (equal (buffer-string) "Text eins"))))

(ert-deftest talktype-test-keeps-writing-into-the-original-buffer ()
  (let ((other (generate-new-buffer "*talktype-other*")))
    (unwind-protect
        (talktype-test--in-buffer "Original"
          (talktype-begin)
          (talktype-append " eins")
          (set-window-buffer (selected-window) other)
          (talktype-append " zwei")
          (talktype-end)
          (should (equal (buffer-string) "Original eins zwei"))
          (should (equal (with-current-buffer other (buffer-string)) "")))
      (kill-buffer other))))

(ert-deftest talktype-test-stops-when-the-buffer-is-killed ()
  (let ((buffer (generate-new-buffer "*talktype-gone*")))
    (set-window-buffer (selected-window) buffer)
    (talktype-begin)
    (kill-buffer buffer)
    (should-error (talktype-append " eins") :type 'user-error)
    (talktype-end)
    (should-not talktype--overlay)))

(ert-deftest talktype-test-begin-closes-a-dictation-left-open ()
  (talktype-test--in-buffer "x"
    (talktype-begin)
    (talktype-append " alt")
    (talktype-begin)
    (talktype-append " neu")
    (talktype-end)
    (should (equal (buffer-string) "x alt neu"))
    (should-not (get-char-property 3 'face))))

;; The commands used through M-x.

(ert-deftest talktype-test-all-four-are-commands ()
  (dolist (f '(talktype-begin talktype-append
               talktype-replace-region talktype-end))
    (should (commandp f))))

(ert-deftest talktype-test-commands-work-interactively ()
  (talktype-test--in-buffer "Hallo"
    (call-interactively #'talktype-begin)
    (should (overlayp talktype--overlay))
    (should (eq (overlay-buffer talktype--overlay) buffer))
    (cl-letf (((symbol-function 'read-string) (lambda (&rest _) " Welt")))
      (call-interactively #'talktype-append))
    (should (equal (buffer-string) "Hallo Welt"))
    (cl-letf (((symbol-function 'read-string) (lambda (&rest _) " du")))
      (call-interactively #'talktype-replace-region))
    (should (equal (buffer-string) "Hallo du"))
    (call-interactively #'talktype-end)
    (should-not talktype--overlay)
    (should (equal (buffer-string) "Hallo du"))))

(ert-deftest talktype-test-interactive-begin-refuses-messages ()
  (let ((previous (window-buffer (selected-window))))
    (unwind-protect
        (progn
          (set-window-buffer (selected-window) (messages-buffer))
          (should-error (call-interactively #'talktype-begin)
                        :type 'user-error)
          (should-not talktype--overlay))
      (set-window-buffer (selected-window) previous))))

(ert-deftest talktype-test-append-without-begin-is-refused ()
  (should-error (talktype-append "x") :type 'user-error))

;;; talktype-test.el ends here
