/**
 * Titipan Kenangan KP JDN - Main Javascript
 */

document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss alerts after 6 seconds
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'opacity 0.5s ease';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 500);
    }, 6000);
  });

  // Setup drag and drop for upload dropzones
  setupDropzone('dropzone-gambar', 'gambar');
  setupDropzone('dropzone-video', 'video');
});

function setupDropzone(dropzoneId, inputId) {
  const dropzone = document.getElementById(dropzoneId);
  const input = document.getElementById(inputId);
  if (!dropzone || !input) return;

  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.style.borderColor = 'var(--gold-primary)';
      dropzone.style.background = 'rgba(212, 175, 55, 0.1)';
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.style.borderColor = 'rgba(212, 175, 55, 0.35)';
      dropzone.style.background = 'rgba(14, 23, 47, 0.6)';
    }, false);
  });

  dropzone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      input.files = files;
      // Trigger appropriate preview
      if (inputId === 'gambar') {
        previewImage(input);
      } else if (inputId === 'video') {
        previewVideo(input);
      }
    }
  });
}
