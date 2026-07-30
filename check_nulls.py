from sqlalchemy import create_engine, text

engine = create_engine('mysql+pymysql://root:@127.0.0.1/skincare_analyzer')

try:
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(text("SHOW TABLES")).fetchall()]
        
        null_counts = {}
        
        for table in tables:
            columns = conn.execute(text(f"DESCRIBE {table}")).fetchall()
            nullable_cols = [col[0] for col in columns if col[2] == 'YES']
            
            if not nullable_cols:
                continue
                
            selects = [f"SUM(CASE WHEN `{col}` IS NULL THEN 1 ELSE 0 END) as `{col}_nulls`" for col in nullable_cols]
            query = f"SELECT {', '.join(selects)} FROM `{table}`"
            
            result = conn.execute(text(query)).fetchone()
            
            for i, col in enumerate(nullable_cols):
                if result and result[i] and result[i] > 0:
                    if table not in null_counts:
                        null_counts[table] = []
                    null_counts[table].append((col, result[i]))
                    
        if null_counts:
            for table, cols in null_counts.items():
                print(f'Table: {table}')
                for col, count in cols:
                    print(f'  - {col}: {count} NULLs')
        else:
            print('No NULLs found in the database!')
except Exception as e:
    print(f'Error: {e}')
