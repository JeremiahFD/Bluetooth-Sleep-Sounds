// One browser/Android picker accepts audio and artwork; split the selection by extension.
export const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp'];
export function classifyMediaFiles(files, audioExtensions) {
  const audio = [], image = [];
  for (const file of Array.from(files ?? [])) {
    const suffix = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (audioExtensions.includes(suffix)) audio.push(file);
    else if (IMAGE_EXTENSIONS.includes(suffix)) image.push(file);
    else throw new Error('Unsupported file ' + file.name + '. Choose an audio recording and/or a JPG, PNG, WebP image.');
  }
  if (audio.length > 1 || image.length > 1)
    throw new Error('Choose at most one audio file and one thumbnail at a time.');
  return {audio:audio[0] ?? null, image:image[0] ?? null};
}
