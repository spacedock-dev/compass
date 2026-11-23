/** Sample a layout measurement until it holds through two consecutive animation frames. */
export async function settledLayout<T>(
  read: () => T,
  equal: (previous: T, next: T) => boolean = Object.is,
): Promise<T> {
  let previous = read();
  for (let steady = 0, frame = 0; frame < 60; frame += 1) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const next = read();
    steady = equal(previous, next) ? steady + 1 : 0;
    if (steady === 2) return next;
    previous = next;
  }
  throw new Error('Layout did not settle within 60 animation frames');
}

export function settledRect(element: Pick<Element, 'getBoundingClientRect'>): Promise<DOMRect> {
  return settledLayout(
    () => element.getBoundingClientRect(),
    (a, b) => a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height,
  );
}
