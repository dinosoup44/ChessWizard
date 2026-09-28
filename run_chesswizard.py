"""Desktop entry with lifetime protection before importing UI or profile code."""
from application_lifetime import retain_application_lifetime

if __name__ == "__main__":
    try:
        retain_application_lifetime()
    except RuntimeError as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), "ChessWizard setup in progress", 0x10)
        raise SystemExit(21)
    from merlin_ui.application import main
    main()
