# Behavioral Simulation Engine

**Since:** v1.7.0

The behavioral simulation engine generates human-like interaction patterns for browser automation. It operates at two levels: a **utility API** for generating movement/typing/scroll/click vectors, and **CDP-level simulators** that dispatch real Chrome DevTools Protocol input events.

## Why Behavioral Simulation?

Automated browsers can be detected by unnatural interaction patterns:
- **Mouse movement** that snaps instantly between points
- **Keystrokes** at perfectly uniform intervals
- **Scrolling** at constant speed without momentum
- **Clicks** landing dead-centre of every element

These simulators introduce human-like variance — trajectories with overshoot, typing with bursts and pauses, scrolling with momentum decay, and clicks with spatial jitter.

## Utility API (`BehavioralSimulator`)

Located in `src/behavioral_sim.py`. All methods are static — no instance needed.

### Mouse Movement — `wind_mouse_bezier()`

Hybrid algorithm: WindMouse physics for macro-trajectory (wind + gravity forces), Bezier micro-correction for smooth landing.

```python
from behavioral_sim import BehavioralSimulator

result = BehavioralSimulator.wind_mouse_bezier(
    start_x=100, start_y=100,
    dest_x=500, dest_y=300,
    gravity=9.0, wind=3.0,
)

print(f"Duration: {result.duration_ms}ms")
print(f"Steps: {result.steps}")
print(f"Trajectory: {result.points[:3]}...{result.points[-3:]}")
```

Parameters control the movement profile:

| Param | Default | Range | Effect |
|-------|---------|-------|--------|
| `gravity` | 9.0 | 1–20 | Pull toward destination — higher = straighter path |
| `wind` | 3.0 | 1–10 | Random lateral force — higher = more curved |
| `max_step` | 15.0 | 5–50 | Max pixels per step — higher = faster |
| `target_threshold` | 12.0 | 5–50 | Px distance to switch to Bezier landing |

### Keystroke Timing — `keystroke_timing()`

Generates per-character timing with realistic dwell/flight distributions and ~5% typo probability.

```python
timing = BehavioralSimulator.keystroke_timing(
    "Hello, world!",
    wpm_range=(40, 80),
)

for t in timing[:5]:
    print(f"  '{t['char']}' — dwell={t['dwell_ms']}ms, flight={t['flight_ms']}ms")
```

**Output:**
```
  'H' — dwell=142ms, flight=213ms
  'e' — dwell=118ms, flight=187ms
  'l' — dwell=95ms, flight=156ms
  'l' — dwell=103ms, flight=244ms
  'o' — dwell=127ms, flight=198ms
```

| Character Type | Dwell (ms) | Flight (ms) |
|---------------|-----------|-------------|
| Home-row letters (a,s,d,f...) | 80–120 | 100–300 |
| Uppercase & symbols | 100–250 | 150–500 |
| Punctuation | 120–200 | 200–400 |
| After typo backspace | N/A | 300–800 (hesitation) |

### Scroll Sequence — `scroll_sequence()`

Momentum-based scroll with power-law velocity decay and optional overshoot.

```python
scroll = BehavioralSimulator.scroll_sequence(
    viewport_height=1080,
    target_pixels=800,
)

print(f"Steps: {len(scroll['steps'])}")
print(f"Duration: {scroll['duration_ms']}ms")
print(f"Overshot: {scroll['overshot']}")
```

The scroll uses an Incomplete Gamma distribution for velocity decay: fast start, gradual slowdown. ~30% of calls include an overshoot+micro-correction at the end.

### Click Position — `click_position()`

Adds Gaussian spatial jitter around an element's centre.

```python
click = BehavioralSimulator.click_position({
    "x": 200, "y": 150, "w": 100, "h": 40,
})

print(f"Actual click: ({click['x']}, {click['y']})")
print(f"Offset from centre: {click['offset_px']}px")
```

Jitter follows a normal distribution with sigma=4px. 99.7% of clicks land within 12px of centre — indistinguishable from human targeting.

## CDP-Level Simulators

Located in `src/anti_detection/behavioral_simulation.py`. Each simulator dispatches real CDP commands via WebSocket.

### MouseSimulator

Generates cubic Bezier paths with variable velocity and dispatches `Input.dispatchMouseEvent` events.

```python
import asyncio
from anti_detection.behavioral_simulation import MouseSimulator

async def demo():
    sim = MouseSimulator()
    events = await sim.human_mouse_move(
        cdp_ws_url="ws://127.0.0.1:9222/devtools/page/...",
        from_x=100, from_y=200,
        to_x=500, to_y=400,
        velocity_ms=400,  # ms per 200px of travel
    )
    print(f"Dispatched {len(events)} mouse move events")

asyncio.run(demo())
```

### TypingSimulator

Dispatches `Input.dispatchKeyEvent` with realistic timing per character. Includes `keyDown`, `keyPress`, and `keyUp` for each character, plus backspace corrections for ~3% of keystrokes.

```python
from anti_detection.behavioral_simulation import TypingSimulator

async def demo():
    sim = TypingSimulator()
    result = await sim.human_type(
        cdp_ws_url="ws://127.0.0.1:9222/...",
        text="Hello, world!",
        wpm=60,
    )
    print(f"Typed {result.chars_typed} chars, {result.typos} typos, "
          f"in {result.total_ms:.0f}ms")
```

### ScrollSimulator

Dispatches `Input.dispatchMouseEvent` with `type="mouseWheel"` events. Momentum follows power-law decay.

```python
from anti_detection.behavioral_simulation import ScrollSimulator

async def demo():
    sim = ScrollSimulator()
    result = await sim.human_scroll(
        cdp_ws_url="ws://127.0.0.1:9222/...",
        delta_y=800,  # scroll down 800px
    )
    print(f"Scrolled {result.total_pixels}px, "
          f"overshot: {result.overshot}")
```

### ClickSimulator

Dispatches `Input.dispatchMouseEvent` with `type="mousePressed"` + `"mouseReleased"`. Click position includes Gaussian jitter.

```python
from anti_detection.behavioral_simulation import ClickSimulator

async def demo():
    sim = ClickSimulator()
    result = await sim.human_click(
        cdp_ws_url="ws://127.0.0.1:9222/...",
        x=250, y=180,
    )
    print(f"Clicked at ({result.x:.0f}, {result.y:.0f}), "
          f"offset from target: {result.offset_px:.1f}px")
```

### TabFocusSimulator

Simulates focus/blur events as a real user would experience them — losing focus for 10–60 seconds at unpredictable intervals.

```python
from anti_detection.behavioral_simulation import TabFocusSimulator

async def demo():
    sim = TabFocusSimulator()
    # Schedule focus loss after 15s, return after 23s
    await sim.simulate_focus_loss(
        cdp_ws_url="ws://127.0.0.1:9222/...",
        delay_before_loss=15.0,
        duration_seconds=23.0,
    )
```

## Detection Risk Comparison

| Signal | Without Simulation | With Simulation |
|--------|-------------------|-----------------|
| Mouse trajectory | Instant snap → target | WindMouse + Bezier curve, 200-800ms |
| Keystroke interval | Uniform 50ms or random | 80-500ms dwell/flight with ~5% typos |
| Scroll velocity | Constant 100px/step | Power-law decay, 30% overshoot |
| Click position | Exact centre (±0px) | Gaussian jitter (±4px σ) |
| Tab focus | Always focused | 10-60s focus loss cycles |

## When to Use Each Layer

- **Utility API** (`BehavioralSimulator`): Use when you need movement/timing vectors for your own automation framework. Works standalone without CDP.
- **CDP Simulators** (`anti_detection.behavioral_simulation`): Use when you have a CDP WebSocket URL and want real browser input events dispatched directly.
