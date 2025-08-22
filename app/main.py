# app/main.py
import os
import sys
import logging
import argparse
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from simple_term_menu import TerminalMenu
from PIL import Image, ImageOps

from app.styles import STYLE_PROMPT_MAP, style_choices
from app.openai_client import generate_image
from uploader import DreamCasterUploader
from utils import ensure_dir, sha256_bytes
import fade


GALLERY_DIR = Path("gallery")
DEFAULT_DEVICE_URL = "http://192.168.1.239"

load_dotenv('.env')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("dreamcaster.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("dreamcaster")

def read_banner():
    try:
        if os.path.exists('res/banners/banner.txt'):
            with open('res/banners/banner.txt', 'r', encoding='utf-8') as f:
                banner_text = f.read()
                print(fade.pinkred(banner_text))

        if os.path.exists('res/banners/banner0.txt'):
            with open('res/banners/banner0.txt', 'r', encoding='utf-8') as f:
                banner_text = f.read()
                print(fade.greenblue(banner_text).strip())
    except Exception as e:
        print(f"Could not print banner: {e}")

def pick_style() -> str:
    
    choices = style_choices()

    
    status_bar_provider = lambda style_name: STYLE_PROMPT_MAP.get(style_name, "No description available.")

    style_menu = TerminalMenu(
        choices,
        title="Select a style",
        menu_cursor="> ",
        menu_cursor_style=("fg_red", "bold"),
        menu_highlight_style=("fg_yellow", "underline"),
        status_bar=status_bar_provider,
        status_bar_style=("fg_cyan",),  
        cycle_cursor=True,
        clear_screen=True,
    )
    style_idx = style_menu.show()

    if style_idx is None:
        sys.exit(0)

    style_key = choices[style_idx]

    fmt_menu = TerminalMenu(
        ["High Art GIF", "Static JPG"],
        title=f"Select output type for '{style_key}'",
        menu_cursor="> ",
        menu_cursor_style=("fg_red", "bold"),
        menu_highlight_style=("fg_yellow", "underline"),
        cycle_cursor=True,
        clear_screen=True,
    )
    fmt_idx = fmt_menu.show()
    if fmt_idx is None:
        sys.exit(0)

    if fmt_idx == 0:
        return f"{style_key}:GIF"
    else:
        return f"{style_key}:JPG"


def prompt_for_description() -> str:
    try:
        art_desc = fade.greenblue("Describe your artwork: ")
        return input(art_desc).strip()
    except KeyboardInterrupt:
        print()
        sys.exit(1)


def build_prompt(style_key: str, user_desc: str) -> str:
    gif_hint = " Looping subtle animation. 240x240. Transparent background."
    animated = style_key.endswith(":GIF")
    base_key = style_key.split(":")[0]
    style_text = STYLE_PROMPT_MAP.get(base_key, "")
    extra = gif_hint if animated else ""
    return f"{style_text}\nSubject: {user_desc}.{extra}"


def ensure_240_rgba(png_bytes: bytes) -> Image.Image:
    im = Image.open(BytesIO(png_bytes)).convert("RGBA")
    im = ImageOps.fit(im, (240, 240), method=Image.LANCZOS, centering=(0.5, 0.5))
    return im


def save_jpg_240(im_rgba: Image.Image, out_path: Path) -> None:
    bg = Image.new("RGB", im_rgba.size, (255, 255, 255))
    bg.paste(im_rgba, mask=im_rgba.split()[-1])
    bg.save(out_path, format="JPEG", quality=95, optimize=True)


def save_gif_240(im_rgba: Image.Image, out_path: Path) -> None:
    pal = im_rgba.convert("P", palette=Image.ADAPTIVE, colors=255)
    alpha = im_rgba.getchannel("A")
    transparent_index = 255
    pal.info["transparency"] = transparent_index
    mask = Image.eval(alpha, lambda a: 255 if a <= 1 else 0)
    pal.paste(transparent_index, mask=mask)
    pal.save(
        out_path,
        save_all=True,
        loop=0,
        optimize=True,
        transparency=transparent_index,
        duration=120,
        disposal=2,
    )


def ask_send_or_retry() -> str:
    menu = TerminalMenu(["Send to DreamCaster", "Try again", "Exit"], title="What next")
    idx = menu.show()
    if idx is None:
        return "Exit"
    return ["Send", "Retry", "Exit"][idx]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=os.getenv("DREAMCASTER_URL", DEFAULT_DEVICE_URL))
    parser.add_argument("--path", default=os.getenv("DREAMCASTER_PATH", "/image"))
    parser.add_argument("--model", default=os.getenv("OPENAI_IMAGE_MODEL", "gpt-4o"))
    parser.add_argument("--api_key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    if not args.api_key:
        logger.error("OPENAI_API_KEY missing")
        sys.exit(2)

    ensure_dir(GALLERY_DIR)

    while True:
        style_key = pick_style()
        user_desc = prompt_for_description()
        full_prompt = build_prompt(style_key, user_desc)
        animated = style_key.endswith(":GIF")
        fmt = "gif" if animated else "jpg"

        logger.info("Generating %s with style %s", fmt, style_key)
        data = generate_image(
            prompt=full_prompt,
            api_key=args.api_key,
            model=args.model,
            size="1024x1024",
            output_format="png",
            background="opaque",
            timeout=args.timeout,
        )
        if data is None:
            logger.error("Generation failed")
            choice = ask_send_or_retry()
            if choice == "Send":
                up = DreamCasterUploader(base_url=args.device, target_path=args.path, logger=logger)
                ok = up.upload_and_set(out_path)
                if ok:
                    print("Uploaded and set on DreamCaster")
                else:
                    print("Upload or set failed. Check logs.")


        im_rgba = ensure_240_rgba(data)
        out_hash = sha256_bytes(data)[:8]
        if fmt == "gif":
            out_path = GALLERY_DIR / f"art_{out_hash}.gif"
            save_gif_240(im_rgba, out_path)
        else:
            out_path = GALLERY_DIR / f"art_{out_hash}.jpg"
            save_jpg_240(im_rgba, out_path)

        logger.info("Saved %s", out_path)
        print(f"Saved: {out_path}")

        choice = ask_send_or_retry()
        if choice == "Send":
            up = DreamCasterUploader(base_url=args.device, target_path=args.path, logger=logger)
            ok = up.upload_file(out_path)
            if ok:
                print("Uploaded to DreamCaster")
            else:
                print("Upload failed. Check logs.")
        elif choice == "Retry":
            continue
        else:
            break


if __name__ == "__main__":
    read_banner()
    main()