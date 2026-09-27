"""Release identity shared by UI and diagnostics; changed only by an explicit release decision."""
PRODUCT_NAME = "ChessWizard"
VERSION = "1.0.0-beta"
DISPLAY_VERSION = f"{PRODUCT_NAME} {VERSION}"


def window_title(section: str) -> str:
    return f"{DISPLAY_VERSION} - {section}"
