# Card Game Pictures

A collection of pixel art images designed for card games, featuring fantasy-style humanoid dinosaur warriors and mages.

## About

This repository contains AI-generated pixel art images suitable for card games. Each image features a single monster character in a fantasy setting.

## Categories

- **dinosaurs** - Humanoid dinosaur warriors and mages
- **godzilla** - Godzilla-inspired creatures
- **cats** - Feline characters
- **bears** - Bear characters
- **monsters** - Various monsters
- **rats** - Rat characters

## Generation Tool

All images in this repository were generated using the [Perchance AI Pixel Art Generator](https://perchance.org/ai-pixel-art-generator).

The prompt used for generation:
> Pixel art card game in fantasy style with dinosaur as humanoid warriors and mages, single monster on image

### Example configuration

The generation was configured with the following settings screenshot:

![System settings used for generation](system_settings.png)

### Prompt (as stored in `prompt.txt`)

```
please generate for me pixel art card game in fanasty style with dinosaur as a humanoids wariors and mages. single monster on image

https://perchance.org/ai-pixel-art-generator
```

## Card Generation

A Python script generates card PNGs from XCF templates with text layers defined in `properties.json`.

### Prerequisites

```bash
# System dependencies
sudo apt install gimp fonts-ebgaramond fonts-firacode

# Python tooling
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Usage

```bash
make init              # verify all dependencies
make generate          # generate cards (Polish, default)
CARD_LANG=en make generate  # generate for another language
make generate-all      # generate all languages
make clean             # remove output/
```

## Files

- `.jpeg` files - Generated pixel art images
- `.xcf` files - GIMP project files for editing
- `.png` files - Processed/exported images
- `template.xcf` / `template.png` - Card templates

## License

This project is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0).

You are free to:
- **Share** - Copy and redistribute the material in any medium or format
- **Adapt** - Remix, transform, and build upon the material for any purpose, even commercially

Under the following terms:
- **Attribution** - You must give appropriate credit, provide a link to the license, and indicate if changes were made. You may do so in any reasonable manner, but not in any way that suggests the licensor endorses you or your use.

For more information, see: https://creativecommons.org/licenses/by/4.0/

## Contributing

Feel free to use these images in your own projects! If you create new variations or improvements, contributions are welcome.
