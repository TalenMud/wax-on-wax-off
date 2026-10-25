"""lerobot-train with oneDNN off: its aarch64 JIT crashes ("label is too far") in the
sharpness augmentation on the GX10. Forked DataLoader workers inherit the flag."""
import torch

torch.backends.mkldnn.enabled = False

if __name__ == "__main__":  # DataLoader workers are spawned: they re-import this file (and the flag above)
    from lerobot.scripts.lerobot_train import main

    main()
