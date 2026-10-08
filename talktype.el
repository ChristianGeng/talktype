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
  "The last closed dictation: (BUFFER START-MARKER END-MARKER TEXT EDITED).
The end marker does not advance: text inserted at the end stays
outside the remembered region.  EDITED is non-nil when the region
stopped holding what TalkType wrote while it was open.")

(defvar talktype--written ""
  "Text TalkType wrote into the open dictation region.
Compared with the region's content: any difference means something
else -- the user, a change hook -- touched it.")

(defvar talktype--edited nil
  "Non-nil once the open dictation held something TalkType did not write.
Set when a write finds the region different from `talktype--written';
stays set when that write replaces the foreign text, so it is still
remembered that something else touched the dictation.")

(defun talktype--mode-line-show ()
  "Add the REC indicator to `global-mode-string', unless turned off.
The indicator goes on the default value, so a buffer-local
`global-mode-string' in whatever buffer is current cannot swallow it."
  (when talktype-mode-line
    (let ((global (default-value 'global-mode-string)))
      (unless (listp global)
        (setq global (list global)))
      (unless (member talktype--mode-line-indicator global)
        (set-default 'global-mode-string
                     (append global (list talktype--mode-line-indicator)))))))

(defun talktype--mode-line-hide ()
  "Remove the REC indicator from `global-mode-string'."
  (let ((global (default-value 'global-mode-string)))
    (when (listp global)
      (set-default 'global-mode-string
                   (delete talktype--mode-line-indicator global)))))

(defun talktype--refuse (format-string &rest args)
  "Signal a `user-error' from FORMAT-STRING and ARGS, prefixed with TalkType.
The reason is also shown with `message' first: an error in a call
through `emacsclient --eval' goes back to emacsclient only, not to the
echo area."
  (let ((reason (apply #'format-message
                       (concat "TalkType: " format-string) args)))
    (message "%s" reason)
    (user-error "%s" reason)))

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
      ;; A foreign edit since the last write shows as a region that no
      ;; longer holds `talktype--written'.  Remember it before the edit
      ;; below, which may overwrite and so erase the foreign text.
      (unless (equal (buffer-substring-no-properties
                      (overlay-start overlay) (overlay-end overlay))
                     talktype--written)
        (setq talktype--edited t))
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
        ;; Keep track of what the region is meant to hold: a foreign
        ;; edit while it is open makes it differ.
        (setq talktype--written
              (concat (substring talktype--written 0
                                 (min (- start region-start)
                                      (length talktype--written)))
                      text
                      (substring talktype--written
                                 (min (- end region-start)
                                      (length talktype--written)))))
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
        (setq talktype--written ""
              talktype--edited nil)
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
    (unwind-protect
        (when (overlayp overlay)
          (let ((dictation-buffer (overlay-buffer overlay))
                (start (overlay-start overlay))
                (end (overlay-end overlay)))
            (when (and dictation-buffer start end)
              ;; Remember for `talktype-undo-last': the start marker
              ;; advances past text inserted at the start, the end
              ;; marker does not, so typing next to the dictation keeps
              ;; it exactly remembered.
              (with-current-buffer dictation-buffer
                (save-restriction
                  (widen)
                  (setq talktype--last
                        (list dictation-buffer
                              (copy-marker start t)
                              (copy-marker end)
                              (buffer-substring-no-properties start end)
                              (or talktype--edited
                                  (not (equal (buffer-substring-no-properties
                                               start end)
                                              talktype--written))))))))))
      (when (overlayp overlay)
        (delete-overlay overlay))
      (when (buffer-live-p buffer)
        (accept-change-group group)
        (when alone
          (undo-amalgamate-change-group group)))))
  t)

(defun talktype--shorten (text)
  "TEXT shortened to one line for the echo area."
  (truncate-string-to-width (subst-char-in-string ?\n ?\s text) 40 nil nil t))

;;;###autoload
(defun talktype-undo-last (&optional text)
  "Delete the last dictation, when its text is still as dictated.
With TEXT, as TalkType's undo key passes it, refuse unless that
dictation wrote exactly TEXT: another dictation ended since.
The dictation that the last `talktype-end' closed is removed from its
buffer as one undo step, from whatever buffer and window is current.
Refuses, changing nothing, while a dictation is open, when nothing is
remembered, or when the dictation was edited -- while it was open or
since it closed -- or its buffer was killed or is now read-only.
Point in the dictation's buffer lands where the text was when it was
inside or at the end of it."
  (interactive)
  (when (and (overlayp talktype--overlay)
             (buffer-live-p (overlay-buffer talktype--overlay)))
    (talktype--refuse "dictation in progress"))
  (unless talktype--last
    (talktype--refuse "no dictation to undo"))
  (when (and text (not (equal text (nth 3 talktype--last))))
    (talktype--refuse "the last dictation is another one"))
  (let ((buffer (nth 0 talktype--last))
        (start (nth 1 talktype--last))
        (end (nth 2 talktype--last))
        (text (nth 3 talktype--last)))
    (unless (buffer-live-p buffer)
      (talktype--refuse "the dictation's buffer is gone"))
    (with-current-buffer buffer
      (when buffer-read-only
        (talktype--refuse "%s is read-only" (buffer-name)))
      (when (nth 4 talktype--last)
        (talktype--refuse "the dictation was edited"))
      (save-restriction
        (widen)
        (unless (equal (buffer-substring-no-properties start end) text)
          (talktype--refuse "the dictation was edited"))
        (let ((group (prepare-change-group buffer))
              ;; An edit sets `deactivate-mark'; an active region or
              ;; evil's visual state must survive removing the dictation.
              (deactivate-mark nil))
          (unwind-protect
              (condition-case nil
                  (progn
                    (activate-change-group group)
                    (delete-region start end))
                (error
                 (talktype--refuse "the dictation cannot be removed")))
            (accept-change-group group)
            (undo-amalgamate-change-group group))))
      (set-marker start nil)
      (set-marker end nil)
      (setq talktype--last nil)
      (message "TalkType: removed last dictation \"%s\""
               (talktype--shorten text))))
  t)

(provide 'talktype)
;;; talktype.el ends here
