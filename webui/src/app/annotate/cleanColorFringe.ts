type CleanResult = {
  pixels: number[];
  outlinePixels: number;
  clearedPixels: number;
  fillIndex: number;
};

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map(at => Number.parseInt(hex.slice(at, at + 2), 16)) as [number, number, number];
}

export function cleanColorFringe(
  pixels: readonly number[], width: number, height: number, palette: readonly string[],
): CleanResult | null {
  if (width < 3 || height < 3 || pixels.length !== width * height) return null;
  const blackIndex = palette.findIndex(hex => hex.toUpperCase() === '#000000');
  if (blackIndex < 0) return null;

  const colors = palette.map(rgb);
  const isVivid = (index: number) => {
    if (index < 0 || index >= colors.length) return false;
    const channels = colors[index];
    return Math.max(...channels) - Math.min(...channels) >= 60 && Math.max(...channels) >= 150;
  };
  const counts = new Map<number, number>();
  let vividTotal = 0;
  for (const index of pixels) {
    if (!isVivid(index)) continue;
    counts.set(index, (counts.get(index) || 0) + 1);
    vividTotal++;
  }
  let fillIndex = -1, fillCount = 0;
  for (const [index, count] of counts) {
    if (count > fillCount) { fillIndex = index; fillCount = count; }
  }
  // This cleanup is intended for flat-color motifs, not multi-color characters.
  if (fillCount < width * height * 0.12 || fillCount < vividTotal * 0.72) return null;

  const neighbors4 = (index: number) => {
    const x = index % width, y = Math.floor(index / width);
    return [x > 0 ? index - 1 : -1, x + 1 < width ? index + 1 : -1,
      y > 0 ? index - width : -1, y + 1 < height ? index + width : -1];
  };
  const visited = new Uint8Array(pixels.length);
  let mainComponent: number[] = [];
  for (let start = 0; start < pixels.length; start++) {
    if (pixels[start] !== fillIndex || visited[start]) continue;
    const component = [start];
    visited[start] = 1;
    for (let head = 0; head < component.length; head++) {
      for (const neighbor of neighbors4(component[head])) {
        if (neighbor >= 0 && !visited[neighbor] && pixels[neighbor] === fillIndex) {
          visited[neighbor] = 1;
          component.push(neighbor);
        }
      }
    }
    if (component.length > mainComponent.length) mainComponent = component;
  }
  if (mainComponent.length < fillCount * 0.8) return null;

  const distance = new Int8Array(pixels.length).fill(-1);
  const queue = [...mainComponent];
  for (const index of mainComponent) distance[index] = 0;
  for (let head = 0; head < queue.length; head++) {
    const index = queue[head];
    if (distance[index] >= 1) continue;
    const x = index % width, y = Math.floor(index / width);
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const nx = x + dx, ny = y + dy;
      if ((!dx && !dy) || nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
      const neighbor = ny * width + nx;
      if (distance[neighbor] !== -1) continue;
      distance[neighbor] = distance[index] + 1;
      queue.push(neighbor);
    }
  }

  const result = [...pixels];
  let outlinePixels = 0, clearedPixels = 0;
  for (let index = 0; index < result.length; index++) {
    if (distance[index] === 1 && result[index] !== blackIndex) {
      result[index] = blackIndex;
      outlinePixels++;
    } else if (distance[index] !== 0 && distance[index] !== 1 && result[index] >= 0) {
      result[index] = -1;
      clearedPixels++;
    }
  }
  return { pixels: result, outlinePixels, clearedPixels, fillIndex };
}
