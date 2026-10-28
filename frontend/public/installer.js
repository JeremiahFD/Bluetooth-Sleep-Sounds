// Compatible with installed build7: use its existing verified native updater.
if (/SleepSoundsAndroid\//.test(navigator.userAgent)) {
  const link = document.getElementById('download-apk');
  link.href = 'sleep-sounds://app-update';
  link.removeAttribute('download');
  link.textContent = 'Install / Update Sleep Sounds';
  document.getElementById('install-help').textContent =
    'Sleep Sounds verifies the update, then Android asks you to confirm. If asked, allow updates from Sleep Sounds and tap this button again.';
}
