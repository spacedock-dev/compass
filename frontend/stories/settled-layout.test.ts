// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { settledLayout, settledRect } from './settled-layout';

describe('settled story layout', () => {
  let frames: FrameRequestCallback[];

  beforeEach(() => {
    frames = [];
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback);
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  async function tick() {
    const callback = frames.shift();
    expect(callback).toBeDefined();
    callback?.(0);
    await Promise.resolve();
  }

  it('requires two consecutive unchanged frames after the scroll offset stops moving', async () => {
    let offset = 0;
    const settled = vi.fn();
    const result = settledLayout(() => offset).then(settled);

    await tick();
    offset = 20;
    await tick();
    await tick();
    expect(settled).not.toHaveBeenCalled();

    await tick();
    await result;
    expect(settled).toHaveBeenCalledWith(20);
  });

  it('waits for the box size even when its origin has stopped moving', async () => {
    let width = 80;
    const element = {
      getBoundingClientRect: () => new DOMRect(10, 20, width, 44),
    };
    const settled = vi.fn();
    const result = settledRect(element).then(settled);

    await tick();
    width = 100;
    await tick();
    await tick();
    expect(settled).not.toHaveBeenCalled();

    await tick();
    await result;
    expect(settled).toHaveBeenCalledWith(new DOMRect(10, 20, 100, 44));
  });

  it('reports a position that never settles', async () => {
    let offset = 0;
    const result = expect(settledLayout(() => offset++)).rejects.toThrow('Layout did not settle');
    for (let frame = 0; frame < 60; frame += 1) await tick();
    await result;
  });
});
