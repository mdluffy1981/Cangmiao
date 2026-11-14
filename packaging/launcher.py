import sys

from katago_gui.bundled import configure_bundle_home


def main() -> int:
    configure_bundle_home(sys.executable)
    from katago_gui.app import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
