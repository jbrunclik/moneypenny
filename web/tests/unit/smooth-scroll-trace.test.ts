/**
 * Characterization of the smooth scroll-to-bottom animation in
 * utils/dom.ts: every scrollTop write, debug event and completion, per
 * frame, for each branch of the animate loop (retarget on a height change,
 * the user scrolling up with and without a height change, momentum, the
 * settle phase and its abort, reduced motion, already at the bottom).
 *
 * iOS momentum and dropped scrollTop writes can only be verified on a
 * device, so a refactor must leave these recordings identical.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Dom = typeof import('@/utils/dom');

describe('smooth scroll-to-bottom write trace', () => {
  let frames: FrameRequestCallback[];
  let now: number;
  let trace: string[];
  let dom: Dom;
  let reducedMotion: boolean;

  beforeEach(async () => {
    frames = [];
    now = 0;
    trace = [];
    reducedMotion = false;
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      frames.push(cb);
      return frames.length;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('reduced-motion') ? reducedMotion : false,
    }));
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    vi.resetModules(); // no user scroll intent or token left from another test
    dom = await import('@/utils/dom');
    dom.setScrollDebugSink((event, data) => trace.push(`${now} debug ${event} ${JSON.stringify(data)}`));
  });

  afterEach(() => {
    dom.setScrollDebugSink(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  interface Scroller extends HTMLElement {
    height: number;
    client: number;
    top: number;
    /** The browser ignores scrollTop writes (iOS momentum, a clamp) */
    drop: boolean;
  }

  function scroller(initialTop = 0): Scroller {
    const el = document.createElement('div') as unknown as Scroller;
    el.height = 2000;
    el.client = 500;
    el.top = initialTop;
    el.drop = false;
    Object.defineProperty(el, 'scrollHeight', { get: () => el.height, configurable: true });
    Object.defineProperty(el, 'clientHeight', { get: () => el.client, configurable: true });
    Object.defineProperty(el, 'scrollTop', {
      get: () => el.top,
      set: (v: number) => {
        trace.push(`${now} write ${Math.round(v * 100) / 100}${el.drop ? ' (dropped)' : ''}`);
        if (!el.drop) el.top = v;
      },
      configurable: true,
    });
    return el;
  }

  function tick(ms = 16): void {
    now += ms;
    const pending = frames.splice(0);
    for (const cb of pending) cb(now);
  }

  function run(el: Scroller, options: { ignoreMomentum?: boolean } = {}): void {
    dom.scrollToBottom(el, true, () => trace.push(`${now} done`), options);
  }

  it('plain run: curve then settle', () => {
    const el = scroller();
    run(el);
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 331.97",
        "64 write 430.62",
        "80 write 523.56",
        "96 write 610.94",
        "112 write 692.96",
        "128 write 769.76",
        "144 write 841.54",
        "160 write 908.44",
        "176 write 970.66",
        "192 write 1028.35",
        "208 write 1081.69",
        "224 write 1130.85",
        "240 write 1176",
        "256 write 1217.31",
        "272 write 1254.95",
        "288 write 1289.09",
        "304 write 1319.9",
        "320 write 1347.56",
        "336 write 1372.22",
        "352 write 1394.08",
        "368 write 1413.28",
        "384 write 1430.02",
        "400 write 1444.44",
        "416 write 1456.74",
        "432 write 1467.07",
        "448 write 1475.61",
        "464 write 1482.53",
        "480 write 1488",
        "496 write 1492.19",
        "512 write 1495.27",
        "528 write 1497.41",
        "544 write 1498.78",
        "560 write 1499.56",
        "576 write 1499.9",
        "592 write 1500",
        "608 write 1500",
        "608 debug bottom-done {"top":1500,"gap":0}",
        "608 done",
      ]
    `);
  });

  it('content grows mid-curve and during the settle: retarget', () => {
    const el = scroller();
    run(el);
    tick();
    tick();
    el.height = 2120; // scroll anchoring above
    el.top += 120;
    tick();
    for (let i = 0; i < 34; i++) tick(); // 592ms: the curve's last frames
    el.height = 2300; // late content: the settle phase keeps pinning
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 358.53",
        "64 write 465.07",
        "80 write 565.44",
        "96 write 659.82",
        "112 write 748.39",
        "128 write 831.34",
        "144 write 908.86",
        "160 write 981.12",
        "176 write 1048.31",
        "192 write 1110.62",
        "208 write 1168.23",
        "224 write 1221.32",
        "240 write 1270.08",
        "256 write 1314.69",
        "272 write 1355.34",
        "288 write 1392.22",
        "304 write 1425.49",
        "320 write 1455.36",
        "336 write 1482",
        "352 write 1505.6",
        "368 write 1526.35",
        "384 write 1544.42",
        "400 write 1560",
        "416 write 1573.28",
        "432 write 1584.44",
        "448 write 1593.66",
        "464 write 1601.13",
        "480 write 1607.04",
        "496 write 1611.56",
        "512 write 1614.89",
        "528 write 1617.2",
        "544 write 1618.68",
        "560 write 1619.52",
        "576 write 1619.9",
        "592 write 1620",
        "608 write 1800",
        "624 write 1800",
        "640 write 1800",
        "656 write 1800",
        "672 write 1800",
        "688 write 1800",
        "704 write 1800",
        "720 write 1800",
        "736 write 1800",
        "752 write 1800",
        "768 write 1800",
        "784 write 1800",
        "800 write 1800",
        "816 write 1800",
        "832 write 1800",
        "848 write 1800",
        "864 write 1800",
        "880 write 1800",
        "896 write 1800",
        "912 write 1800",
        "928 write 1800",
        "944 write 1800",
        "960 write 1800",
        "976 write 1800",
        "992 write 1800",
        "1008 write 1800",
        "1008 debug bottom-done {"top":1800,"gap":0}",
        "1008 done",
      ]
    `);
  });

  it('the user scrolls up in the frame the height changes', () => {
    const el = scroller();
    run(el);
    tick();
    tick();
    dom.noteUserScrollIntent();
    el.top = 10;
    el.height = 2100;
    tick();
    tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 debug bottom-abort-user {"top":10,"expected":227}",
        "48 done",
      ]
    `);
  });

  it('a height change with an upward move and no user input retargets', () => {
    const el = scroller();
    run(el);
    tick();
    tick();
    el.top -= 40; // keyboard closing clamps the list
    el.client = 900;
    tick();
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 243.44",
        "64 write 315.79",
        "80 write 383.94",
        "96 write 448.03",
        "112 write 508.17",
        "128 write 564.49",
        "144 write 617.13",
        "160 write 666.19",
        "176 write 711.82",
        "192 write 754.12",
        "208 write 793.24",
        "224 write 829.29",
        "240 write 862.4",
        "256 write 892.69",
        "272 write 920.29",
        "288 write 945.33",
        "304 write 967.93",
        "320 write 988.21",
        "336 write 1006.3",
        "352 write 1022.32",
        "368 write 1036.41",
        "384 write 1048.68",
        "400 write 1059.26",
        "416 write 1068.28",
        "432 write 1075.85",
        "448 write 1082.12",
        "464 write 1087.19",
        "480 write 1091.2",
        "496 write 1094.27",
        "512 write 1096.53",
        "528 write 1098.1",
        "544 write 1099.11",
        "560 write 1099.67",
        "576 write 1099.93",
        "592 write 1100",
        "608 write 1100",
        "608 debug bottom-done {"top":1100,"gap":0}",
        "608 done",
      ]
    `);
  });

  it('the user scrolls up mid-curve', () => {
    const el = scroller();
    run(el);
    tick();
    tick();
    dom.noteUserScrollIntent();
    el.top = 0;
    tick();
    tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 debug bottom-abort-user {"top":0,"expected":227}",
        "48 done",
      ]
    `);
  });

  it('a downward nudge from other code mid-curve is not the user', () => {
    const el = scroller();
    run(el);
    tick();
    tick();
    el.top += 300;
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 331.97",
        "64 write 430.62",
        "80 write 523.56",
        "96 write 610.94",
        "112 write 692.96",
        "128 write 769.76",
        "144 write 841.54",
        "160 write 908.44",
        "176 write 970.66",
        "192 write 1028.35",
        "208 write 1081.69",
        "224 write 1130.85",
        "240 write 1176",
        "256 write 1217.31",
        "272 write 1254.95",
        "288 write 1289.09",
        "304 write 1319.9",
        "320 write 1347.56",
        "336 write 1372.22",
        "352 write 1394.08",
        "368 write 1413.28",
        "384 write 1430.02",
        "400 write 1444.44",
        "416 write 1456.74",
        "432 write 1467.07",
        "448 write 1475.61",
        "464 write 1482.53",
        "480 write 1488",
        "496 write 1492.19",
        "512 write 1495.27",
        "528 write 1497.41",
        "544 write 1498.78",
        "560 write 1499.56",
        "576 write 1499.9",
        "592 write 1500",
        "608 write 1500",
        "608 debug bottom-done {"top":1500,"gap":0}",
        "608 done",
      ]
    `);
  });

  it('momentum: a coast from a flick just before an automatic scroll stops it, not the button', () => {
    const el = scroller(1000);
    now = 5000;
    dom.noteUserScrollIntent();
    now = 5400;
    run(el);
    el.top -= 30;
    tick();
    tick();
    trace.push('-- button');
    const el2 = scroller(1000);
    run(el2, { ignoreMomentum: true });
    el2.top -= 30;
    tick();
    el2.top -= 30;
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "5400 debug bottom-start {"from":1000,"to":1500,"ch":500}",
        "5416 debug bottom-abort-user {"top":970,"expected":1000}",
        "5416 done",
        "-- button",
        "5432 debug bottom-start {"from":1000,"to":1500,"ch":500}",
        "5448 write 1075.81",
        "5464 write 1143.54",
        "5480 write 1203.65",
        "5496 write 1256.59",
        "5512 write 1302.81",
        "5528 write 1342.78",
        "5544 write 1376.95",
        "5560 write 1405.77",
        "5576 write 1429.7",
        "5592 write 1449.19",
        "5608 write 1464.69",
        "5624 write 1476.67",
        "5640 write 1485.58",
        "5656 write 1491.87",
        "5672 write 1496",
        "5688 write 1498.42",
        "5704 write 1499.59",
        "5720 write 1499.97",
        "5736 write 1500",
        "5752 write 1500",
        "5768 write 1500",
        "5784 write 1500",
        "5800 write 1500",
        "5816 write 1500",
        "5832 write 1500",
        "5832 debug bottom-done {"top":1500,"gap":0}",
        "5832 done",
      ]
    `);
  });

  it('a user move during the settle ends it', () => {
    const el = scroller();
    run(el);
    for (let i = 0; i < 36; i++) tick(); // 576ms: the curve's last frames
    el.height = 2100; // late content keeps it settling
    tick();
    tick();
    dom.noteUserScrollIntent();
    el.top -= 200;
    tick();
    tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 331.97",
        "64 write 430.62",
        "80 write 523.56",
        "96 write 610.94",
        "112 write 692.96",
        "128 write 769.76",
        "144 write 841.54",
        "160 write 908.44",
        "176 write 970.66",
        "192 write 1028.35",
        "208 write 1081.69",
        "224 write 1130.85",
        "240 write 1176",
        "256 write 1217.31",
        "272 write 1254.95",
        "288 write 1289.09",
        "304 write 1319.9",
        "320 write 1347.56",
        "336 write 1372.22",
        "352 write 1394.08",
        "368 write 1413.28",
        "384 write 1430.02",
        "400 write 1444.44",
        "416 write 1456.74",
        "432 write 1467.07",
        "448 write 1475.61",
        "464 write 1482.53",
        "480 write 1488",
        "496 write 1492.19",
        "512 write 1495.27",
        "528 write 1497.41",
        "544 write 1498.78",
        "560 write 1499.56",
        "576 write 1499.9",
        "592 write 1600",
        "608 write 1600",
        "624 debug bottom-abort-user {"top":1400,"expected":1600}",
        "624 done",
      ]
    `);
  });

  it('a small user move while the browser drops our settle writes', () => {
    const el = scroller();
    run(el);
    for (let i = 0; i < 36; i++) tick();
    el.height = 2100;
    tick();
    tick();
    dom.noteUserScrollIntent();
    el.drop = true; // the user's finger holds the list: our writes don't stick
    el.top -= 3;
    tick();
    tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 331.97",
        "64 write 430.62",
        "80 write 523.56",
        "96 write 610.94",
        "112 write 692.96",
        "128 write 769.76",
        "144 write 841.54",
        "160 write 908.44",
        "176 write 970.66",
        "192 write 1028.35",
        "208 write 1081.69",
        "224 write 1130.85",
        "240 write 1176",
        "256 write 1217.31",
        "272 write 1254.95",
        "288 write 1289.09",
        "304 write 1319.9",
        "320 write 1347.56",
        "336 write 1372.22",
        "352 write 1394.08",
        "368 write 1413.28",
        "384 write 1430.02",
        "400 write 1444.44",
        "416 write 1456.74",
        "432 write 1467.07",
        "448 write 1475.61",
        "464 write 1482.53",
        "480 write 1488",
        "496 write 1492.19",
        "512 write 1495.27",
        "528 write 1497.41",
        "544 write 1498.78",
        "560 write 1499.56",
        "576 write 1499.9",
        "592 write 1600",
        "608 write 1600",
        "624 write 1600 (dropped)",
        "640 write 1600 (dropped)",
      ]
    `);
  });

  it('a non-user move during the settle is overwritten', () => {
    const el = scroller();
    run(el);
    for (let i = 0; i < 36; i++) tick();
    el.height = 2100;
    tick();
    tick();
    el.top -= 200;
    for (let i = 0; i < 60; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 116.83",
        "32 write 227.43",
        "48 write 331.97",
        "64 write 430.62",
        "80 write 523.56",
        "96 write 610.94",
        "112 write 692.96",
        "128 write 769.76",
        "144 write 841.54",
        "160 write 908.44",
        "176 write 970.66",
        "192 write 1028.35",
        "208 write 1081.69",
        "224 write 1130.85",
        "240 write 1176",
        "256 write 1217.31",
        "272 write 1254.95",
        "288 write 1289.09",
        "304 write 1319.9",
        "320 write 1347.56",
        "336 write 1372.22",
        "352 write 1394.08",
        "368 write 1413.28",
        "384 write 1430.02",
        "400 write 1444.44",
        "416 write 1456.74",
        "432 write 1467.07",
        "448 write 1475.61",
        "464 write 1482.53",
        "480 write 1488",
        "496 write 1492.19",
        "512 write 1495.27",
        "528 write 1497.41",
        "544 write 1498.78",
        "560 write 1499.56",
        "576 write 1499.9",
        "592 write 1600",
        "608 write 1600",
        "624 write 1600",
        "640 write 1600",
        "656 write 1600",
        "672 write 1600",
        "688 write 1600",
        "704 write 1600",
        "720 write 1600",
        "736 write 1600",
        "752 write 1600",
        "768 write 1600",
        "784 write 1600",
        "800 write 1600",
        "816 write 1600",
        "832 write 1600",
        "848 write 1600",
        "864 write 1600",
        "880 write 1600",
        "896 write 1600",
        "912 write 1600",
        "928 write 1600",
        "944 write 1600",
        "960 write 1600",
        "976 write 1600",
        "992 write 1600",
        "992 debug bottom-done {"top":1600,"gap":0}",
        "992 done",
      ]
    `);
  });

  it('reduced motion jumps, then settles', () => {
    reducedMotion = true;
    const el = scroller();
    run(el);
    for (let i = 0; i < 40; i++) tick();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 debug bottom-start {"from":0,"to":1500,"ch":500}",
        "16 write 1500",
        "32 write 1500",
        "48 write 1500",
        "64 write 1500",
        "80 write 1500",
        "96 write 1500",
        "112 write 1500",
        "128 write 1500",
        "144 write 1500",
        "160 write 1500",
        "176 write 1500",
        "192 write 1500",
        "208 write 1500",
        "224 write 1500",
        "240 write 1500",
        "256 write 1500",
        "272 write 1500",
        "288 write 1500",
        "304 write 1500",
        "320 write 1500",
        "336 write 1500",
        "352 write 1500",
        "368 write 1500",
        "384 write 1500",
        "400 write 1500",
        "400 debug bottom-done {"top":1500,"gap":0}",
        "400 done",
      ]
    `);
  });

  it('already at the bottom: nothing to do', () => {
    const el = scroller(1500);
    run(el);
    tick();
    expect([...trace, `frames=${frames.length}`, `smooth=${dom.isSmoothScrolling()}`]).toMatchInlineSnapshot(`
      [
        "0 done",
        "frames=0",
        "smooth=false",
      ]
    `);
  });
});
