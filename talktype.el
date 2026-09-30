;;; talktype.el --- Receive TalkType dictation through emacsclient -*- lexical-binding: t; -*-

;; Author: Christian Geng
;; URL: https://github.com/ChristianGeng/talktype
;; Package-Requires: ((emacs "27.1"))

;;; Commentary:

;; TalkType streams dictated words into Emacs by calling these functions
;; through `emacsclient --eval', instead of sending keys: with evil in
;; normal state, in the minibuffer, isearch or org-agenda, keys are
;; commands.  The text arrives as a Lisp string argument, so it is only
;; ever inserted, never evaluated.
;;
;; A dictation is a region at point in the selected window's buffer:
;;
;;   (talktype-begin)                  open the region at point
;;   (talktype-append " some words")   insert at the region's end
;;   (talktype-replace-region "text")  replace the whole region
;;   (talktype-end)                    keep the text, close the region
;;
;; While open, the region shows `talktype-provisional'.  It stays in the
;; buffer it was opened in, also when another buffer is selected meanwhile.
;; One dictation is one undo step, unless the buffer was edited otherwise
;; during it.  Point follows the text only when it was at the region's
;; end; the evil state and the mark are not touched.
;;
;; The four are also commands, to try them by hand with M-x.
;;
;; Setup: `(server-start)' and `(require 'talktype)' with this file's
;; directory on `load-path'.

;;; Code:

(require 'seq)

(defgroup talktype nil
  "Dictation from TalkType through emacsclient."
  :group 'convenience
  :prefix "talktype-")

(defface talktype-provisional
  '((t :underline t))
  "Face of dictated text while the dictation is still open."
  :group 'talktype)

(defvar talktype--overlay nil
  "Overlay spanning the open dictation, or nil when none is open.")

(defvar talktype--change-group nil
  "Change group of the open dictation, amalgamated into one undo step.")

(defvar talktype--tick nil
  "`buffer-chars-modified-tick' after the dictation's last edit.
nil once someone else edited the buffer during the dictation.")

(defun talktype--refuse (format-string &rest args)
  "Signal a `user-error' from FORMAT-STRING and ARGS, prefixed with TalkType."
  (apply #'user-error (concat "TalkType: " format-string) args))

(defun talktype--check-writable (buffer)
  "Signal an error unless dictation may go into BUFFER."
  (unless (buffer-live-p buffer)
    (talktype--refuse "the dictation buffer is gone"))
  (with-current-buffer buffer
    (when (minibufferp)
      (talktype--refuse "not dictating into the minibuffer"))
    (when buffer-read-only
      (talktype--refuse "%s is read-only" (buffer-name)))
    (when (bound-and-true-p isearch-mode)
      (talktype--refuse "not dictating during isearch"))))

(defun talktype--region ()
  "The open dictation overlay, after checking its buffer can take text."
  (unless (overlayp talktype--overlay)
    (talktype--refuse "no dictation is open"))
  (talktype--check-writable (overlay-buffer talktype--overlay))
  talktype--overlay)

(defun talktype--put (overlay start end text)
  "Replace START to END in OVERLAY's buffer by TEXT and extend OVERLAY.
Point, in the buffer and in every window showing it, moves to the new
end only if it was at END."
  (let* ((buffer (overlay-buffer overlay))
         (windows (seq-filter (lambda (w) (= (window-point w) end))
                              (get-buffer-window-list buffer nil t))))
    (with-current-buffer buffer
      (unless (eql talktype--tick (buffer-chars-modified-tick))
        (setq talktype--tick nil))
      (let ((follow (= (point) end))
            (region-start (overlay-start overlay))
            ;; An edit sets `deactivate-mark'; evil's visual state and an
            ;; active region must survive dictation.
            (deactivate-mark nil))
        (save-excursion
          (goto-char start)
          (delete-region start end)
          (insert text))
        (move-overlay overlay region-start (+ start (length text)))
        (when follow
          (goto-char (overlay-end overlay)))
        (dolist (w windows)
          (set-window-point w (overlay-end overlay))))
      (when talktype--tick
        (setq talktype--tick (buffer-chars-modified-tick))))))

;;;###autoload
(defun talktype-begin ()
  "Open a dictation region at point in the selected window's buffer.
A dictation still open is closed first."
  (interactive)
  (when talktype--overlay
    (talktype-end))
  (let* ((window (selected-window))
         (buffer (window-buffer window)))
    (talktype--check-writable buffer)
    (with-current-buffer buffer
      (let ((pos (window-point window)))
        ;; Front-advance: text typed at the start stays outside the region.
        (setq talktype--overlay (make-overlay pos pos buffer t nil))
        (overlay-put talktype--overlay 'face 'talktype-provisional)
        (overlay-put talktype--overlay 'talktype t)
        (setq talktype--change-group (prepare-change-group buffer))
        (activate-change-group talktype--change-group)
        (setq talktype--tick (buffer-chars-modified-tick)))))
  t)

;;;###autoload
(defun talktype-append (text)
  "Insert TEXT at the end of the open dictation region."
  (interactive (list (read-string "Text: ")))
  (let* ((overlay (talktype--region))
         (end (overlay-end overlay)))
    (talktype--put overlay end end text))
  t)

;;;###autoload
(defun talktype-replace-region (text)
  "Replace the text of the open dictation region by TEXT."
  (interactive (list (read-string "Text: ")))
  (let ((overlay (talktype--region)))
    (talktype--put overlay (overlay-start overlay) (overlay-end overlay) text))
  t)

;;;###autoload
(defun talktype-end ()
  "Close the open dictation: drop its face, keep its text.
Everything inserted since `talktype-begin' becomes one undo step, unless
the buffer was also edited otherwise meanwhile: one undo would then take
those edits along, so the dictation's steps stay separate."
  (interactive)
  (let* ((overlay talktype--overlay)
         (group talktype--change-group)
         (buffer (and group (caar group)))
         (alone (and talktype--tick (buffer-live-p buffer)
                     (eql talktype--tick
                          (buffer-chars-modified-tick buffer)))))
    (setq talktype--overlay nil
          talktype--change-group nil
          talktype--tick nil)
    (when (overlayp overlay)
      (delete-overlay overlay))
    (when (buffer-live-p buffer)
      (accept-change-group group)
      (when alone
        (undo-amalgamate-change-group group))))
  t)

(provide 'talktype)
;;; talktype.el ends here
