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
;; While open, the region shows `talktype-provisional' and the mode line
;; shows `\='● REC\=' (face `talktype-recording'; `talktype-mode-line'
;; turns that off).  The region stays in the buffer it was opened in,
;; also when another buffer is selected meanwhile.  One dictation is one
;; undo step, unless the buffer was edited otherwise during it.  Point
;; follows the text only when it was at the region's end; the evil state
;; and the mark are not touched.
;;
;; `talktype-undo-last' deletes the last closed dictation again, as one
;; undo step, from any buffer — as long as its text is still exactly what
;; was dictated.  The four calls above are also commands, to try them by
;; hand with M-x.
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

(defface talktype-recording
  '((t :foreground "red" :weight bold))
  "Face of the REC indicator while a dictation is open."
  :group 'talktype)

(defcustom talktype-mode-line t
  "Whether the mode line shows a REC indicator while a dictation is open."
  :type 'boolean
  :group 'talktype)

(defconst talktype--mode-line-indicator
  (propertize " ● REC" 'face 'talktype-recording)
  "Element in `global-mode-string' while a dictation is open.")

(defvar talktype--overlay nil
  "Overlay spanning the open dictation, or nil when none is open.")

(defvar talktype--change-group nil
  "Change group of the open dictation, amalgamated into one undo step.")

(defvar talktype--tick nil
  "`buffer-chars-modified-tick' after the dictation's last edit.
nil once someone else edited the buffer during the dictation.")

(defvar talktype--last nil
  "The last closed dictation: (BUFFER START-MARKER END-MARKER TEXT).
The end marker does not advance: text inserted at the end stays
outside the remembered region.")

(defun talktype--mode-line-show ()
  "Add the REC indicator to `global-mode-string', unless turned off."
  (when talktype-mode-line
    (unless (listp global-mode-string)
      (setq global-mode-string (list global-mode-string)))
    (add-to-list 'global-mode-string talktype--mode-line-indicator t)))

(defun talktype--mode-line-hide ()
  "Remove the REC indicator from `global-mode-string'."
  (when (listp global-mode-string)
    (setq global-mode-string
          (delete talktype--mode-line-indicator global-mode-string))))

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
        (setq talktype--tick (buffer-chars-modified-tick))))
    (talktype--mode-line-show))
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
    (talktype--mode-line-hide)
    (when (overlayp overlay)
      (let ((dictation-buffer (overlay-buffer overlay))
            (start (overlay-start overlay))
            (end (overlay-end overlay)))
        (when (and dictation-buffer start end)
          ;; Remember for `talktype-undo-last': the start marker advances
          ;; past text inserted at the start, the end marker does not, so
          ;; typing next to the dictation keeps it exactly remembered.
          (with-current-buffer dictation-buffer
            (setq talktype--last
                  (list dictation-buffer
                        (copy-marker start t)
                        (copy-marker end)
                        (buffer-substring-no-properties start end)))))
      (delete-overlay overlay)))
    (when (buffer-live-p buffer)
      (accept-change-group group)
      (when alone
        (undo-amalgamate-change-group group))))
  t)

(defun talktype--shorten (text)
  "TEXT shortened to one line for the echo area."
  (truncate-string-to-width (subst-char-in-string ?\n ?\s text) 40 nil nil t))

;;;###autoload
(defun talktype-undo-last ()
  "Delete the last dictation, when its text is still as dictated.
The dictation that the last `talktype-end' closed is removed from its
buffer as one undo step, from whatever buffer and window is current.
Refuses, changing nothing, while a dictation is open, when nothing is
remembered, or when the dictation's text was edited since, its buffer
was killed or is now read-only.  Point in the dictation's buffer lands
where the text was when it was inside or at the end of it."
  (interactive)
  (when (and (overlayp talktype--overlay)
             (buffer-live-p (overlay-buffer talktype--overlay)))
    (talktype--refuse "dictation in progress"))
  (unless talktype--last
    (talktype--refuse "no dictation to undo"))
  (let ((buffer (nth 0 talktype--last))
        (start (nth 1 talktype--last))
        (end (nth 2 talktype--last))
        (text (nth 3 talktype--last)))
    (unless (buffer-live-p buffer)
      (talktype--refuse "the dictation's buffer is gone"))
    (with-current-buffer buffer
      (when buffer-read-only
        (talktype--refuse "%s is read-only" (buffer-name)))
      (unless (equal (buffer-substring-no-properties start end) text)
        (talktype--refuse "the dictation was edited"))
      (let ((group (prepare-change-group buffer))
            ;; An edit sets `deactivate-mark'; an active region or evil's
            ;; visual state must survive removing the dictation.
            (deactivate-mark nil))
        (unwind-protect
            (progn
              (activate-change-group group)
              (delete-region start end))
          (accept-change-group group)
          (undo-amalgamate-change-group group)))
      (set-marker start nil)
      (set-marker end nil)
      (setq talktype--last nil)
      (message "TalkType: removed last dictation \"%s\""
               (talktype--shorten text))))
  t)

(provide 'talktype)
;;; talktype.el ends here
