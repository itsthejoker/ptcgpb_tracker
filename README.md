# PTCGPB Companion

tl;dr: This is a companion desktop app that works with [PTCGPB](https://github.com/kevnITG/PTCGPB) to help you find what cards are in what accounts. 

## The Background

When trying to put together more complex decks, I found myself really wishing for a way to find cards of lesser rarity that PTCGPB doesn't track. Loading every account and logging every card would be more time and effort than it's worth, especially as things change.

## Distribution information

Linux build (distributable ZIP) using uv + PyInstaller

Prerequisites:
- uv installed (see https://docs.astral.sh/uv/)
- zip utility (e.g., sudo apt-get install zip)

Steps:
1. Make the build script executable:
   - `chmod +x ./build-linux.sh`
2. Run the build:
   - `./build-linux.sh`

What it does:
- Invokes PyInstaller via `uvx` to create an onedir bundle for the PyQt6 app with required assets.
- Packages the result as `dist/<name>-<version>-linux.zip`.

Run the packaged app:
- `unzip dist/<name>-<version>-linux.zip`
- `./<name>/<name>`

Notes:
- Entry point is `main.py` (PyQt6 GUI).
- Assets included: `resources/card_imgs`, `resources/styles`, `resources/static`, and `templates`.
- You can override the output name/version: `APP_NAME=cardcounter-app APP_VERSION=0.1.0 ./build-linux.sh`
