"""Comprehensive test suite for XLight."""
import sys

def run_tests():
    from xlight import (
        create_gamma_backend, HardwareBrightnessBackend,
        _kelvin_to_rgb_multiplier, load_config, save_config,
        t, XLightApp
    )

    passed = 0
    failed = 0

    # Test 1: Gamma backend
    try:
        g = create_gamma_backend()
        displays = g.get_displays()
        assert len(displays) >= 1
        print(f"TEST 1 - Gamma backend: {len(displays)} display(s) found - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 1 - Gamma backend: FAIL ({e})", flush=True)
        failed += 1

    # Test 2: Hardware backend
    try:
        h = HardwareBrightnessBackend()
        print(f"TEST 2 - HW backend available: {h.available} - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 2 - HW backend: FAIL ({e})", flush=True)
        failed += 1

    # Test 3: Color temp 6500K (daylight)
    try:
        r, gv, b = _kelvin_to_rgb_multiplier(6500)
        assert 0.95 <= r <= 1.05, f"Red should be ~1.0, got {r}"
        assert 0.90 <= gv <= 1.05, f"Green should be ~1.0, got {gv}"
        print(f"TEST 3 - Color temp 6500K: R={r:.2f} G={gv:.2f} B={b:.2f} - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 3 - Color temp 6500K: FAIL ({e})", flush=True)
        failed += 1

    # Test 4: Color temp 3200K (warm)
    try:
        r, gv, b = _kelvin_to_rgb_multiplier(3200)
        assert r > gv > b, f"Warm should have R>G>B, got R={r:.2f} G={gv:.2f} B={b:.2f}"
        print(f"TEST 4 - Color temp 3200K: R={r:.2f} G={gv:.2f} B={b:.2f} - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 4 - Color temp 3200K: FAIL ({e})", flush=True)
        failed += 1

    # Test 5: Config load
    try:
        cfg = load_config()
        assert "brightness" in cfg
        assert "profiles" in cfg
        assert "temperature" in cfg
        print(f"TEST 5 - Config load: OK - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 5 - Config load: FAIL ({e})", flush=True)
        failed += 1

    # Test 6: Config save/load roundtrip
    try:
        cfg = load_config()
        original = cfg.get("brightness", 100)
        cfg["brightness"] = 75
        save_config(cfg)
        cfg2 = load_config()
        assert cfg2["brightness"] == 75
        cfg2["brightness"] = original
        save_config(cfg2)
        print(f"TEST 6 - Config save/load roundtrip: OK - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 6 - Config save/load: FAIL ({e})", flush=True)
        failed += 1

    # Test 7: i18n
    try:
        en = t("brightness", "en")
        vi = t("brightness", "vi")
        assert en != vi, "EN and VI should be different"
        assert en == "Brightness"
        assert len(vi) > 0, "Vietnamese translation should not be empty"
        print(f"TEST 7 - i18n: translations OK (en!=vi verified) - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 7 - i18n: FAIL ({e})", flush=True)
        failed += 1

    # Test 8: GUI creation
    try:
        app = XLightApp()
        assert len(app.displays) >= 1
        for d in app.displays:
            assert "name" in d
            assert "gamma_id" in d
            assert "hw_supported" in d
        print(f"TEST 8 - GUI created: {len(app.displays)} display(s) - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 8 - GUI creation: FAIL ({e})", flush=True)
        failed += 1

    # Test 9: Gamma set/reset
    try:
        for d in app.displays:
            g.set_gamma(d["gamma_id"], 0.8, 5000)
        for d in app.displays:
            g.reset_gamma(d["gamma_id"])
        print(f"TEST 9 - Gamma set/reset: OK - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 9 - Gamma set/reset: FAIL ({e})", flush=True)
        failed += 1

    # Test 10: Profile system
    try:
        profiles = cfg.get("profiles", {})
        assert "Day" in profiles
        assert "Night" in profiles
        assert profiles["Day"]["brightness"] == 100
        assert profiles["Night"]["temperature"] == 3200
        print(f"TEST 10 - Profiles: {len(profiles)} presets - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 10 - Profiles: FAIL ({e})", flush=True)
        failed += 1

    # Test 11: Color temp boundary values
    try:
        r1, _, _ = _kelvin_to_rgb_multiplier(1000)
        assert r1 == 1.0, "At 1000K red should be 1.0"
        _, _, b1 = _kelvin_to_rgb_multiplier(10000)
        assert b1 == 1.0, "At 10000K blue should be 1.0"
        print(f"TEST 11 - Color temp boundaries: OK - PASS", flush=True)
        passed += 1
    except Exception as e:
        print(f"TEST 11 - Color temp boundaries: FAIL ({e})", flush=True)
        failed += 1

    # Cleanup
    try:
        app.root.destroy()
    except Exception:
        pass

    print(flush=True)
    print(f"{'='*40}", flush=True)
    print(f"Results: {passed} passed, {failed} failed / {passed + failed} total", flush=True)
    if failed == 0:
        print("ALL TESTS PASSED!", flush=True)
    else:
        print("SOME TESTS FAILED!", flush=True)
    print(f"{'='*40}", flush=True)

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
