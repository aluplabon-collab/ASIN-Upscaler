import os
import sys
# Add current directory to path so image_processor_core is found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import image_processor_core # type: ignore

def test_sheet_logic():
    print("=== Testing Core Upscaler Sheet Logic ===")
    sheet_id = "1_9cfiZT92a-1Whj3v5H71v-yKxjwyqx0Rqc5TGpiEw0"
    worksheet_name = "Sheet3"
    
    print(f"Connecting to sheet {sheet_id} [{worksheet_name}] via core logic...")
    try:
        sheet = image_processor_core._get_sheet(sheet_id, worksheet_name)
        print("Connected successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Mock data that process_single_product would generate
    mock_urls = [
        "https://vps.example.com/img1.jpg",
        "https://vps.example.com/img2.jpg"
    ]
    row_idx = 1 # Simulating line 1 from the GUI text area (row 6)
    
    upscaled_str = "|".join([u for u in mock_urls if u])
    
    print(f"Attempting to write URLs to row {5 + row_idx} under 'Item photo URL' header...")
    try:
        headers = sheet.row_values(5)
        col_idx = None
        for idx_c, h in enumerate(headers, 1):
            if h.strip().lower() == "item photo url":
                col_idx = idx_c
                break

        if col_idx is None:
            col_idx = len(headers) + 1
            headers.append("Item photo URL")
            sheet.update(values=[headers], range_name=f"A5") # update row 5 headers
            print("  Created new 'Item photo URL' column.")

        row_num = 5 + row_idx
        sheet.update_cell(row_num, col_idx, upscaled_str)
        print(f"SUCCESSFULLY updated Sheet row {row_num}, col {col_idx} with links: {upscaled_str}")
        
    except Exception as e:
        print(f"Failed to update sheet: {e}")

if __name__ == "__main__":
    test_sheet_logic()
