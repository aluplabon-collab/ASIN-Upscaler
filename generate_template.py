import os
from PIL import Image, ImageDraw, ImageFont # type: ignore

def generate_best_seller_template(out_path="templates/best_seller_frame.png", size=(1000, 1000)):
    # Create a completely transparent RGBA image
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. Red Border (Outer)
    border_width = 30
    border_color = (255, 0, 0, 255)  # Solid Red
    draw.rectangle([0, 0, size[0], size[1]], outline=border_color, width=border_width)
    
    # Optional: Load a font, fallback to default if missing
    try:
        # Try to use Arial or a standard sans-serif
        font_large = ImageFont.truetype("arialbd.ttf", 60)
        font_small = ImageFont.truetype("arialbd.ttf", 30)
    except IOError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # 2. Top-Left BEST SELLER Ribbon
    # We draw a red polygon in the top-left corner
    ribbon_poly = [
        (0, 0),
        (350, 0),
        (400, 50),
        (350, 100),
        (0, 100)
    ]
    draw.polygon(ribbon_poly, fill=border_color)
    draw.text((20, 10), "ITEM AVAILABLE", font=font_small, fill=(255, 255, 255, 255))
    draw.text((20, 40), "BEST SELLER", font=font_large, fill=(255, 255, 255, 255))

    # 3. Bottom-Left USA Flag
    # Draw simple representative stripes and a blue canton since we don't have a flag asset
    flag_w, flag_h = 250, 150
    flag_x, flag_y = border_width, size[1] - flag_h - border_width
    
    # Draw 13 stripes (alternating red and white)
    stripe_h = flag_h / 13
    for i in range(13):
        color = (255, 0, 0, 255) if i % 2 == 0 else (255, 255, 255, 255)
        sy = flag_y + (i * stripe_h)
        draw.rectangle([flag_x, sy, flag_x + flag_w, sy + stripe_h], fill=color)
        
    # Blue Canton
    canton_w = flag_w * 0.4
    canton_h = stripe_h * 7
    draw.rectangle([flag_x, flag_y, flag_x + canton_w, flag_y + canton_h], fill=(0, 0, 128, 255))
    
    # A few white stars (rough dots)
    star_color = (255, 255, 255, 255)
    for r in range(5):
        for c in range(6):
            sx = flag_x + 10 + (c * 15)
            sy = flag_y + 8 + (r * 15)
            draw.ellipse([sx, sy, sx+4, sy+4], fill=star_color)

    # 4. Bottom-Right BEST PRICE Banner
    # This one is a tilted polygon
    banner_w, banner_h = 450, 120
    banner_x = size[0] - banner_w - border_width + 30
    banner_y = size[1] - banner_h - border_width - 20
    
    banner_poly = [
        (banner_x, banner_y + 40),
        (banner_x + banner_w, banner_y - 20),
        (banner_x + banner_w, banner_y + banner_h - 20),
        (banner_x, banner_y + banner_h)
    ]
    draw.polygon(banner_poly, fill=border_color)
    
    # We have to draw text on a separate transparent image, rotate it, and paste it
    txt_img = Image.new("RGBA", (banner_w, banner_h), (0,0,0,0))
    txt_draw = ImageDraw.Draw(txt_img)
    try:
        font_banner = ImageFont.truetype("arialbd.ttf", 70)
    except IOError:
        font_banner = font_large
        
    txt_draw.text((20, 20), "BEST PRICE", font=font_banner, fill=(255, 255, 255, 255))
    txt_img = txt_img.rotate(8, expand=True) # Rotate degrees
    img.paste(txt_img, (banner_x - 10, banner_y - 10), txt_img)

    # Save to templates directory
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, format="PNG")
    print(f"Generated template: {out_path}")

if __name__ == "__main__":
    generate_best_seller_template()
