"""Behavioral Engine — automatikus emberi bemenet a CDPClient számára.

A session-enként konzisztens profilt generál (seed=session_id) és a
valós CDP parancsokat küld (Input.dispatchMouseEvent/KeyEvent) emberi
időzítéssel.

A CDPClient nem hívja meg közvetlenül — helyette a _apply_behavioral_hooks()
metódus kicseréli a session scroll/type/click metódusait emberiesített
verzióra, ha a session profilja engedélyezi a behavioral módot.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import dataclass
from typing import Any

from behavioral_scroll import BehavioralScroll
from behavioral_sim import BehavioralSimulator, MouseMovementResult

# ── Session Profiles ──────────────────────────────────────────────────────


@dataclass
class HumanProfile:
    """Egy session emberi profiltulajdonságai."""

    # Gépelés
    wpm_range: tuple[int, int] = (45, 80)
    typo_rate: float = 0.04
    # Egér
    mouse_gravity: float = 9.0
    mouse_wind: float = 3.0
    mouse_max_step: float = 15.0
    # Görgetés
    scroll_mode: str = "auto"  # smooth / jagged / auto
    scroll_step_min: int = 100
    scroll_step_max: int = 800
    # Késleltetés szorzó (0.7 = gyorsabb, 1.3 = lassabb)
    speed_factor: float = 1.0
    # Engedélyezve?
    enabled: bool = True

    @classmethod
    def from_session(cls, session_id: str | None) -> HumanProfile:
        """Egyedi profilt generál a session azonosítóból (seedelten)."""
        if not session_id:
            return cls()
        # Hash → seed → determinisztikus random
        h = hashlib.sha256(session_id.encode()).hexdigest()
        seed = int(h[:8], 16)
        rng = random.Random(seed)

        wpm_min = rng.randint(40, 60)
        wpm_max = rng.randint(wpm_min + 10, wpm_min + 40)
        gravity = round(rng.uniform(6.0, 12.0), 1)
        wind = round(rng.uniform(1.5, 5.0), 1)
        max_step = round(rng.uniform(10.0, 20.0), 1)
        speed = round(rng.uniform(0.7, 1.3), 2)

        return cls(
            wpm_range=(wpm_min, wpm_max),
            typo_rate=rng.uniform(0.02, 0.06),
            mouse_gravity=gravity,
            mouse_wind=wind,
            mouse_max_step=max_step,
            scroll_mode=rng.choice(["smooth", "jagged", "auto"]),
            scroll_step_min=rng.randint(80, 150),
            scroll_step_max=rng.randint(400, 800),
            speed_factor=speed,
        )


# ── Behavioral Engine ─────────────────────────────────────────────────────


class BehavioralEngine:
    """Kezeli az emberi bemeneteket egy CDP kliens számára."""

    def __init__(self, cdp_client: Any, profile: HumanProfile | None = None):
        self._client = cdp_client
        self._profile = profile or HumanProfile()
        self._last_mouse_pos: tuple[float, float] = (0.0, 0.0)
        self._sim = BehavioralSimulator()
        self._scroll = BehavioralScroll()

    @property
    def profile(self) -> HumanProfile:
        return self._profile

    # ── Mouse ────────────────────────────────────────────────────────

    async def move_mouse_to(self, dest_x: float, dest_y: float) -> None:
        """Emberi görbével mozgatja az egeret a jelenlegi pozícióból."""
        if not self._profile.enabled:
            return
        start_x, start_y = self._last_mouse_pos
        result: MouseMovementResult = self._sim.wind_mouse_bezier(
            start_x, start_y, dest_x, dest_y,
            gravity=self._profile.mouse_gravity,
            wind=self._profile.mouse_wind,
            max_step=self._profile.mouse_max_step,
        )
        # Mindegyik pontot CDP mouseMoved eseményként küldjük
        base_delay = result.duration_ms / max(1, len(result.points))
        for px, py in result.points:
            await self._send_mouse_event(
                "mouseMoved", px, py, self._last_mouse_pos
            )
            self._last_mouse_pos = (px, py)
            # Emberi sebesség variáció (+- 30%)
            jitter = random.uniform(0.7, 1.3) * self._profile.speed_factor
            await asyncio.sleep(base_delay * jitter / 1000.0)
        self._last_mouse_pos = (dest_x, dest_y)

    async def click_at(
        self, dest_x: float, dest_y: float, button: str = "left"
    ) -> None:
        """Emberi görbével mozgat, majd kattint."""
        await self.move_mouse_to(dest_x, dest_y)
        # Lenyomás
        await self._send_mouse_event(
            "mousePressed", dest_x, dest_y, self._last_mouse_pos,
            button=button
        )
        # Emberi késleltetés lenyomás és felengedés között
        delay = random.uniform(50, 150) * self._profile.speed_factor
        await asyncio.sleep(delay / 1000.0)
        # Felengedés
        await self._send_mouse_event(
            "mouseReleased", dest_x, dest_y, self._last_mouse_pos,
            button=button
        )

    async def _send_mouse_event(
        self,
        event_type: str,
        x: float,
        y: float,
        prev: tuple[float, float] = (0.0, 0.0),
        button: str = "left",
    ) -> None:
        """Küld egy Input.dispatchMouseEvent CDP parancsot."""
        params: dict[str, Any] = {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "buttons": 1 if event_type != "mouseMoved" else 0,
            "clickCount": 1 if "mouse" in event_type else 0,
        }
        if self._client._connected and self._client._ws:
            import json as _json

            try:
                self._client._message_id += 1
                msg_id = self._client._message_id
                payload = {
                    "id": msg_id,
                    "method": "Input.dispatchMouseEvent",
                    "params": params,
                }
                await self._client._ws.send(_json.dumps(payload))
                # Nem várunk választ (fire-and-forget) — az Input események
                # nem adnak vissza értéket.
            except Exception:
                pass  # ha a kapcsolat megszakadt, csendben tovább

    # ── Keyboard ─────────────────────────────────────────────────────

    async def type_text(self, selector: str, text: str) -> dict:
        """Gépelés emberi időzítéssel (dwell/flight), előbb az elemre kattintva."""
        if not self._profile.enabled:
            return await self._client.type_text(selector, text)

        # 1. Kattint az elemre (hogy a focus rákerüljön)
        elem = await self._client.evaluate(
            f"(() => {{ const e = document.querySelector({selector!r}); "
            f"if (!e) return null; const r = e.getBoundingClientRect(); "
            f"return {{x: r.x + r.width/2, y: r.y + r.height/2}}; }})()"
        )
        if elem and isinstance(elem, dict) and elem.get("result") is not None:
            pos = elem["result"]
            if isinstance(pos, dict) and "x" in pos:
                await self.click_at(pos["x"], pos["y"])
        else:
            # Nincs ilyen elem a DOM-ban — ne gépeljünk a levegőbe.
            return {
                "status": "error",
                "error": f"Element not found: {selector}",
            }

        # 2. Gépelés dwell/flight időzítéssel
        keystrokes = self._sim.keystroke_timing(
            text, wpm_range=self._profile.wpm_range
        )
        for ks in keystrokes:
            char = ks["char"]
            dwell = ks.get("dwell_ms", 120) * self._profile.speed_factor
            flight = ks.get("flight_ms", 250) * self._profile.speed_factor

            if char == "\b":
                # Backspace
                await self._send_key_event("Backspace")
            else:
                await self._send_key_event(char, shift=char.isupper() or char in '!@#$%^&*()_+{}|:"<>?')

            await asyncio.sleep(dwell / 1000.0)
            await self._send_key_event(char, type_="keyUp",
                                       shift=char.isupper() or char in '!@#$%^&*()_+{}|:"<>?')
            await asyncio.sleep(flight / 1000.0)

        return {"status": "ok", "operation": "behavioral_type", "result": {"chars": len(text)}}

    async def _send_key_event(
        self, key: str, type_: str = "keyDown", shift: bool = False
    ) -> None:
        """Küld egy Input.dispatchKeyEvent CDP parancsot."""
        if not (self._client._connected and self._client._ws):
            return
        import json as _json

        params: dict[str, Any] = {
            "type": type_,
            "key": key,
            "code": f"Key{key.upper()}" if len(key) == 1 and key.isalpha() else "",
            "text": key if type_ == "keyDown" and len(key) == 1 else "",
            "unmodifiedText": key if type_ == "keyDown" and len(key) == 1 else "",
            "modifiers": 2 if shift else 0,
        }
        try:
            self._client._message_id += 1
            payload = {
                "id": self._client._message_id,
                "method": "Input.dispatchKeyEvent",
                "params": params,
            }
            await self._client._ws.send(_json.dumps(payload))
        except Exception:
            pass

    # ── Scroll ───────────────────────────────────────────────────────

    async def scroll(
        self, distance: int, viewport_height: int = 800
    ) -> list[dict]:
        """Emberi görgetés az adott távolságba, session profil szerinti módban."""
        if not self._profile.enabled:
            return []

        self._scroll.update_config(
            mode=self._profile.scroll_mode,
            step_min=self._profile.scroll_step_min,
            step_max=self._profile.scroll_step_max,
        )
        events = await self._scroll.scroll(distance, 0)
        for evt in events:
            delta = evt.get("delta_y", 0)
            delay = evt.get("delay_ms", 20) * self._profile.speed_factor
            pause = evt.get("pause_after", 0) * self._profile.speed_factor

            if self._client._connected and self._client._ws:
                import json as _json

                try:
                    self._client._message_id += 1
                    payload = {
                        "id": self._client._message_id,
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": "mouseWheel",
                            "x": 400,
                            "y": 400,
                            "deltaX": 0,
                            "deltaY": delta,
                        },
                    }
                    await self._client._ws.send(_json.dumps(payload))
                except Exception:
                    pass

            await asyncio.sleep((delay + pause) / 1000.0)

        return events
