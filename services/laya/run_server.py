"""Run the upstream Laya service on loopback with one pinned checkpoint."""
import argparse
import os
from runtime import configure_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--allow-downloads", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    configure_environment()
    os.environ.update({
        "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(args.port), "LAYA_DEVICE": args.device,
        "LAYA_PRELOAD": "1", "LAYA_MODELS": "multilingual", "LAYA_MAX_LOADED": "1",
        "LAYA_DEFAULT_MODEL": "multilingual", "LAYA_AUTO_TASK": "0", "LAYA_THREADS": "4",
        "LAYA_MAX_CONCURRENT": "1", "LAYA_JEV_STRICT": "0",
        "LAYA_TOURNAMENT_GROUP": "0", "HF_HUB_OFFLINE": "0" if args.allow_downloads else "1",
    })
    import torch
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; select --device cpu explicitly")
    from laya.serve import main as serve
    serve()


if __name__ == "__main__":
    main()
