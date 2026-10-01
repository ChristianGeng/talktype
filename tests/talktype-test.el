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
       (setq talktype--last nil)
       (talktype--mode-line-hide)
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

;; `talktype-undo-last'.

(ert-deftest talktype-test-undo-last-removes-only-the-dictation ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (talktype-append " Welt")
    (talktype-end)
    ;; Typing elsewhere afterwards stays.
    (insert " von mir")
    (goto-char 7)
    (talktype-undo-last)
    (should (equal (buffer-string) "Hallo von mir"))
    ;; Point was inside the dictation: it lands where the text was.
    (should (= (point) 6))
    ;; Removed and forgotten.
    (should-error (talktype-undo-last) :type 'user-error)
    (should (equal (buffer-string) "Hallo von mir"))))

(ert-deftest talktype-test-undo-last-is-one-undo-step ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (dolist (words '(" eins" " zwei"))
      (talktype-append words)
      (undo-boundary))
    (talktype-end)
    (undo-boundary)
    (talktype-undo-last)
    (should (equal (buffer-string) "Hallo"))
    (talktype-test--undo-once)
    (should (equal (buffer-string) "Hallo eins zwei"))))

(ert-deftest talktype-test-undo-last-works-from-another-buffer ()
  (let ((other (generate-new-buffer "*talktype-other*")))
    (unwind-protect
        (talktype-test--in-buffer "Hallo"
          (talktype-begin)
          (talktype-append " Welt")
          (talktype-end)
          (set-window-buffer (selected-window) other)
          (with-current-buffer other
            (insert "untouched")
            (talktype-undo-last))
          (should (equal (buffer-string) "Hallo"))
          (should (equal (with-current-buffer other (buffer-string))
                         "untouched")))
      (kill-buffer other))))

(ert-deftest talktype-test-undo-last-refuses-an-edited-dictation ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (talktype-append " Welt")
    (talktype-end)
    (goto-char 9)
    (insert "X")
    (should-error (talktype-undo-last) :type 'user-error)
    (should (equal (buffer-string) "Hallo WeXlt"))))

(ert-deftest talktype-test-undo-last-refuses-a-read-only-buffer ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (talktype-append " Welt")
    (talktype-end)
    (setq buffer-read-only t)
    (should-error (talktype-undo-last) :type 'user-error)
    (should (equal (buffer-string) "Hallo Welt"))))

(ert-deftest talktype-test-undo-last-refuses-a-killed-buffer ()
  (talktype-test--in-buffer "x"
    (talktype-begin)
    (talktype-append " Welt")
    (talktype-end)
    (kill-buffer buffer)
    (should-error (talktype-undo-last) :type 'user-error)))

(ert-deftest talktype-test-undo-last-refuses-nothing-remembered ()
  (talktype-test--in-buffer "x"
    (setq talktype--last nil)
    (should-error (talktype-undo-last) :type 'user-error)))

(ert-deftest talktype-test-undo-last-refuses-while-dictating ()
  (talktype-test--in-buffer "x"
    (talktype-begin)
    (talktype-append " noch offen")
    (should-error (talktype-undo-last) :type 'user-error)
    (should (equal (buffer-string) "x noch offen"))))

(ert-deftest talktype-test-undo-last-is-a-command ()
  (should (commandp 'talktype-undo-last)))

;; The REC indicator.

(ert-deftest talktype-test-mode-line-while-a-dictation-is-open ()
  (talktype-test--in-buffer "x"
    (should-not (member talktype--mode-line-indicator global-mode-string))
    (talktype-begin)
    (should (member talktype--mode-line-indicator global-mode-string))
    (talktype-append " eins")
    (should (member talktype--mode-line-indicator global-mode-string))
    (talktype-end)
    (should-not (member talktype--mode-line-indicator global-mode-string))))

(ert-deftest talktype-test-mode-line-gone-after-a-failed-begin ()
  (let ((ro (generate-new-buffer "*talktype-ro*")))
    (unwind-protect
        (talktype-test--in-buffer "x"
          (talktype-begin)
          (talktype-append " alt")
          (should (member talktype--mode-line-indicator global-mode-string))
          ;; The next begin closes the left-over dictation first, then
          ;; refuses in the read-only buffer: nothing stays open.
          (with-current-buffer ro (setq buffer-read-only t))
          (set-window-buffer (selected-window) ro)
          (should-error (talktype-begin) :type 'user-error)
          (should-not talktype--overlay)
          (should-not (member talktype--mode-line-indicator
                              global-mode-string)))
      (kill-buffer ro))))

(ert-deftest talktype-test-mode-line-stays-off-when-turned-off ()
  (let ((talktype-mode-line nil))
    (talktype-test--in-buffer "x"
      (talktype-begin)
      (talktype-append " eins")
      (should-not (member talktype--mode-line-indicator global-mode-string))
      (talktype-end))))

(ert-deftest talktype-test-mode-line-indicator-says-rec ()
  (should (equal talktype--mode-line-indicator " ● REC"))
  (should (eq (get-text-property 0 'face talktype--mode-line-indicator)
              'talktype-recording)))

;; Edits that are not TalkType's.

(ert-deftest talktype-test-undo-last-refuses-an-edit-during-dictation ()
  (talktype-test--in-buffer "x"
    (talktype-begin)
    (talktype-append "hello")
    ;; An edit inside the open region is not TalkType's, so undoing the
    ;; dictation must not take it along.
    (goto-char 4)
    (insert "X")
    (talktype-end)
    (should-error (talktype-undo-last) :type 'user-error)
    (should (equal (buffer-string) "xheXllo"))))

(ert-deftest talktype-test-undo-last-ignores-edits-outside-the-dictation ()
  (talktype-test--in-buffer "Hallo"
    (talktype-begin)
    (talktype-append " Welt")
    ;; An edit next to the open region stays outside it.
    (goto-char (point-min))
    (insert "!")
    (talktype-end)
    (talktype-undo-last)
    (should (equal (buffer-string) "!Hallo"))))

;; Narrowing.

(ert-deftest talktype-test-end-closes-a-dictation-while-narrowed ()
  (talktype-test--in-buffer "Hallo\nWelt\n"
    (talktype-begin)
    (talktype-append " eins")
    ;; The dictation is outside the restriction: end still closes it.
    (narrow-to-region 1 7)
    (talktype-end)
    (should-not talktype--overlay)
    (should-not (member talktype--mode-line-indicator global-mode-string))
    (widen)
    (should (equal (buffer-string) "Hallo\nWelt\n eins"))
    (should-not (get-char-property 13 'face))
    (should talktype--last)
    (talktype-undo-last)
    (should (equal (buffer-string) "Hallo\nWelt\n"))))

(ert-deftest talktype-test-undo-last-works-while-narrowed ()
  (talktype-test--in-buffer "Hallo\nWelt\n"
    (talktype-begin)
    (talktype-append " eins")
    (talktype-end)
    (narrow-to-region 1 7)
    (talktype-undo-last)
    (widen)
    (should (equal (buffer-string) "Hallo\nWelt\n"))))

;; `global-mode-string' is global state, not the current buffer's.

(ert-deftest talktype-test-mode-line-hits-the-default-value ()
  (talktype-test--in-buffer "x"
    ;; A buffer-local value must not swallow the indicator.
    (setq-local global-mode-string '("local"))
    (talktype-begin)
    (should (member talktype--mode-line-indicator
                    (default-value 'global-mode-string)))
    (should-not (member talktype--mode-line-indicator global-mode-string))
    (talktype-end)
    (should-not (member talktype--mode-line-indicator
                        (default-value 'global-mode-string)))
    (should (equal global-mode-string '("local")))))

;;; talktype-test.el ends here
