# Skincare Analyzer Backend

Backend API untuk Skincare Analyzer menggunakan FastAPI, Google Gemini AI, dan RAG (Retrieval-Augmented Generation).

## 🚀 Features

- **OCR Processing** - Extract text dari gambar produk skincare
- **Ingredient Matching** - Match ingredient dengan database MySQL
- **RAG Context** - Retrieve informasi dari dataset 1000+ ingredient
- **AI Analysis** - Analisis menggunakan Google Gemini dengan context grounding
- **Expert System** - Rule-based analysis untuk safety scoring
- **User Authentication** - Firebase Auth & Google Sign-In
- **History Management** - Simpan dan kelola riwayat analisis

## 📦 Installation

### Prerequisites
- Python 3.9+
- MySQL/MariaDB (Laragon)
- Tesseract OCR
- Google Gemini API Key

### Setup

```bash
# Clone repository
git clone <repository-url>
cd skincare-analyzer-backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.production.example .env
# Edit .env dengan credentials Anda
```

### Environment Variables

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=skincare_analyzer

# Google Gemini AI
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

# RAG Configuration
RAG_INGREDIENT_DATASET=data/dataset_scincare/cosmetic_ingredients_train.csv
RAG_FUZZY_THRESHOLD=0.84
RAG_MAX_CONTEXT_ITEMS=12

# Security
SECRET_KEY=your_secret_key
MONITORING_API_KEY=your_monitoring_key

# Firebase (optional)
FIREBASE_CREDENTIALS=path/to/firebase-credentials.json
```

## 🗄️ Database Setup

```sql
-- Import database schema
mysql -u root -p skincare_analyzer < database/schema.sql

-- Import ingredient data
mysql -u root -p skincare_analyzer < database/ingredients.sql
```

## 🏃 Run Server

```bash
# Development
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

Server akan berjalan di: `http://localhost:8000`

API Docs: `http://localhost:8000/docs`

## 📊 Dataset

Backend menggunakan **3 dataset terintegrasi** di `data/dataset_scincare/`:

1. **cosmetic_ingredients_train.csv** - 1000+ ingredient dengan deskripsi lengkap (untuk RAG)
   - Ingredient name & detailed description
   - What it is, what it does
   - Benefits and side effects

2. **ingredients_category.csv** - 500+ ingredient dengan kategori lengkap (untuk RAG)
   - Functions (primary & secondary)
   - Warnings
   - Origin (Natural/Synthetic)
   - Charge type (Ionic/Non-ionic)

3. **Database Kosmetik Mengandung Bahan Berbahaya.csv** - Data BPOM (untuk RAG)
   - Harmful/banned ingredients by BPOM
   - Products containing harmful ingredients
   - Public warning numbers

**Semua 3 dataset digunakan bersamaan** untuk memberikan context yang komprehensif ke AI!

## 🤖 RAG Architecture

```
User Input (OCR Text)
    ↓
Text Cleaning & Tokenization
    ↓
Ingredient Matching (MySQL Database)
    ↓
RAG Multi-Source Context Retrieval
    ├─ Dataset 1: Descriptions (1000+ ingredients)
    ├─ Dataset 2: Categories & Functions (500+ ingredients)
    └─ Dataset 3: BPOM Harmful Ingredients
    │
    ├─ Exact Match
    └─ Fuzzy Match (84% threshold)
    ↓
Merge Data from All 3 Sources
    ↓
Build Comprehensive Prompt with Context
    ├─ Database Context (MySQL)
    ├─ Descriptions Context (CSV 1)
    ├─ Categories Context (CSV 2)
    └─ BPOM Warnings Context (CSV 3)
    ↓
Google Gemini AI Analysis
    ├─ Model: gemini-2.5-flash
    ├─ Fallback: gemini-2.0-flash, gemini-1.5-flash
    └─ Context-Grounded Response (3 sources)
    ↓
Expert System Scoring
    ↓
Final Analysis Result
```

## 📡 API Endpoints

### Public Endpoints
- `POST /analyze` - Analyze ingredient text
- `POST /analyze-image` - Analyze ingredient dari gambar
- `GET /analysis/{id}` - Get analysis detail
- `GET /analysis-history` - Get recent analyses

### Authenticated Endpoints
- `POST /history/save` - Save analysis to user history
- `GET /history` - Get user's saved history

### Auth Endpoints
- `POST /auth/google` - Google Sign-In
- `POST /auth/register` - Register user
- `POST /auth/login` - Login user

### Monitoring Endpoints (requires API key)
- `GET /health` - Health check
- `GET /metrics/summary` - System metrics
- `GET /metrics/recent` - Recent analyses
- `GET /metrics/users` - User statistics
- `GET /metrics/ingredients` - Ingredient statistics

## 🔧 Configuration Files

- `main.py` - FastAPI application
- `modules/gemini_ai.py` - Gemini AI integration
- `modules/rag_context.py` - RAG context retrieval
- `modules/expert_system.py` - Rule-based analysis
- `modules/ingredient_matching.py` - Ingredient matching logic
- `database/db_connection.py` - Database connection

## 🧪 Testing

```bash
# Test API
curl http://localhost:8000/

# Test analysis
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Water, Glycerin, Niacinamide"}'
```

## 🚀 Deployment

### VPS Deployment

```bash
# Install dependencies
sudo apt update
sudo apt install python3-pip python3-venv tesseract-ocr

# Setup application
cd /var/www/skincare-analyzer-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run with systemd or supervisor
sudo systemctl start skincare-analyzer
```

### Docker Deployment (Optional)

```bash
docker build -t skincare-analyzer-backend .
docker run -p 8000:8000 skincare-analyzer-backend
```

## 📝 Notes

- RAG menggunakan fuzzy matching dengan threshold 84% untuk mencocokkan ingredient
- Gemini AI memiliki fallback ke model lain jika primary model gagal
- Dataset CSV di-cache untuk performa optimal
- Semua analisis disimpan ke database untuk tracking

## 📄 License

[Your License]
