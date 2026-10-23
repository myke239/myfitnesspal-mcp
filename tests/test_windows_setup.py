from myfitnesspal_mcp.windows_setup import verification_failure


def test_verification_failure_preserves_safe_diagnostic():
    message = verification_failure("Firefox", "Could not access MyFitnessPal.")
    assert "Could not access MyFitnessPal." in message
    assert "Firefox profile" in message


def test_chromium_verification_failure_suggests_firefox():
    message = verification_failure("Chrome", "Cannot read chrome cookies.")
    assert "Cannot read chrome cookies." in message
    assert "try Firefox" in message


def test_verification_failure_has_fallback_without_diagnostic():
    message = verification_failure("Edge", "")
    assert "Could not verify your sign-in in Edge." in message
    assert "choose Firefox" in message
