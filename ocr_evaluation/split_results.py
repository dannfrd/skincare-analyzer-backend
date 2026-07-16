import os
import csv

def split_csv_by_engine(input_path, output_dir, engines):
    if not os.path.exists(input_path):
        print(f"[Warning] File not found: {input_path}")
        return
    
    print(f"Processing {os.path.basename(input_path)}...")
    
    # Read rows
    with open(input_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
        
    # Determine the engine column name
    engine_col = None
    for col in fieldnames:
        if col.lower() in ['engine', 'engine ocr']:
            engine_col = col
            break
            
    if not engine_col:
        print(f"[Error] Engine column not found in {input_path}")
        return
        
    # Group rows by engine
    grouped_rows = {eng.lower(): [] for eng in engines}
    for row in rows:
        val = row[engine_col].lower()
        if val in grouped_rows:
            grouped_rows[val].append(row)
        else:
            # Check substring match
            matched = False
            for eng in engines:
                if eng.lower() in val:
                    grouped_rows[eng.lower()].append(row)
                    matched = True
                    break
            if not matched:
                print(f"[Info] Row with engine value '{row[engine_col]}' skipped/not matched.")
                
    # Write files
    filename_w_ext = os.path.basename(input_path)
    filename, ext = os.path.splitext(filename_w_ext)
    
    base_name = filename
    # Check if the filename already has an engine suffix and strip it
    for eng in engines:
        if base_name.endswith(f"_{eng.lower()}"):
            base_name = base_name[:-len(f"_{eng.lower()}")]
            
    for eng in engines:
        eng_rows = grouped_rows[eng.lower()]
        if not eng_rows:
            continue
            
        out_filename = f"{base_name}_{eng.lower()}{ext}"
        out_path = os.path.join(output_dir, out_filename)
        
        with open(out_path, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(eng_rows)
            
        print(f"  Created: {out_filename} ({len(eng_rows)} rows)")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(base_dir, "results")
    separated_dir = os.path.join(results_dir, "separated")
    
    os.makedirs(separated_dir, exist_ok=True)
    
    engines = ["tesseract", "mlkit", "paddleocr"]
    
    files_to_split = [
        os.path.join(results_dir, "summary_results.csv"),
        os.path.join(results_dir, "summary_results_skenario_2.csv"),
        os.path.join(results_dir, "missed_ingredients_skenario_1.csv"),
        os.path.join(results_dir, "missed_ingredients_skenario_2.csv"),
    ]
    
    # Split files into the 'separated' folder
    for file_path in files_to_split:
        split_csv_by_engine(file_path, separated_dir, engines)
        
    # Clean up the split files that might be in the parent 'results' directory
    print("\nCleaning up split files from parent results directory...")
    for filename in os.listdir(results_dir):
        if filename.endswith(".csv"):
            # Check if it has an engine suffix
            name_lower = filename.lower()
            if any(name_lower.endswith(f"_{eng}.csv") for eng in engines):
                file_to_remove = os.path.join(results_dir, filename)
                try:
                    os.remove(file_to_remove)
                    print(f"  Removed: {filename}")
                except Exception as e:
                    print(f"  Failed to remove {filename}: {e}")

if __name__ == "__main__":
    main()
