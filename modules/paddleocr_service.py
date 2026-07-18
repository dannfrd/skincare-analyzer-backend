import os
import sys
import time
import json
import logging
import io
from typing import Union, Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Coba impor library eksternal secara aman
try:
    import requests
except ImportError:
    requests = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import cv2
except ImportError:
    cv2 = None


class PaddleOCRVLAPIProcessor:
    """
    Menangani ekstraksi teks & parsing dokumen menggunakan layanan Cloud AI Studio API
    dari PaddleOCR Vision-Language Model (PaddleOCR-VL-1.6 / v2 API).
    Sangat cocok untuk tata letak dokumen kompleks, tabel, dan daftar bahan kosmetik berkolom.
    """
    def __init__(
        self,
        token: Optional[str] = None,
        job_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: int = 120,
        poll_interval: int = 3,
        optional_payload: Optional[Dict[str, Any]] = None
    ):
        self.token = token or os.getenv("PADDLE_OCR_TOKEN", "e405fa4354b84189a36608489e18adf1663e8b53")
        self.job_url = job_url or os.getenv("PADDLE_OCR_API_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
        self.model = model or os.getenv("PADDLE_OCR_MODEL", "PaddleOCR-VL-1.6")
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.optional_payload = optional_payload or {
            "useDocOrientationClassify": True,
            "useDocUnwarping": True,
            "useChartRecognition": False,
        }

    def _prepare_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"bearer {self.token}",
        }

    def submit_job(self, image_path_or_array: Union[str, Any]) -> str:
        """
        Mengirimkan job OCR ke PaddleOCR Cloud API.
        Mendukung URL string (http/https), path file lokal, maupun numpy array image.
        Mengembalikan jobId (str).
        """
        if requests is None:
            raise RuntimeError("Library 'requests' belum terinstal. Silakan jalankan 'pip install requests'.")

        headers = self._prepare_headers()

        # 1. Mode URL (http:// atau https://)
        if isinstance(image_path_or_array, str) and image_path_or_array.startswith("http"):
            logger.info(f"Submitting PaddleOCR-VL job (URL Mode): {image_path_or_array}")
            headers["Content-Type"] = "application/json"
            payload = {
                "fileUrl": image_path_or_array,
                "model": self.model,
                "optionalPayload": self.optional_payload
            }
            response = requests.post(self.job_url, json=payload, headers=headers)

        # 2. Mode File Lokal Path
        elif isinstance(image_path_or_array, str):
            if not os.path.exists(image_path_or_array):
                raise FileNotFoundError(f"File gambar tidak ditemukan di path: {image_path_or_array}")
            logger.info(f"Submitting PaddleOCR-VL job (Local File Mode): {image_path_or_array}")
            data = {
                "model": self.model,
                "optionalPayload": json.dumps(self.optional_payload)
            }
            with open(image_path_or_array, "rb") as f:
                files = {"file": f}
                response = requests.post(self.job_url, headers=headers, data=data, files=files)

        # 3. Mode Numpy Array (misal dari kamera/preprocessing OpenCV)
        elif np is not None and isinstance(image_path_or_array, np.ndarray):
            logger.info("Submitting PaddleOCR-VL job (Numpy Array / In-Memory Mode)")
            if cv2 is None:
                raise RuntimeError("OpenCV (cv2) diperlukan untuk mengodekan gambar dari numpy array.")
            
            # Encode ke buffer JPEG dalam memori
            success, encoded_image = cv2.imencode('.jpg', image_path_or_array, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if not success:
                raise RuntimeError("Gagal mengodekan gambar numpy array ke format JPEG.")
            
            data = {
                "model": self.model,
                "optionalPayload": json.dumps(self.optional_payload)
            }
            image_bytes = encoded_image.tobytes()
            files = {"file": ("image.jpg", image_bytes, "image/jpeg")}
            response = requests.post(self.job_url, headers=headers, data=data, files=files)

        else:
            raise ValueError(f"Tipe input tidak didukung: {type(image_path_or_array)}")

        if response.status_code != 200:
            logger.error(f"Gagal mengirim job PaddleOCR-VL: Status {response.status_code} | Respon: {response.text}")
            raise RuntimeError(f"PaddleOCR API Submission Error ({response.status_code}): {response.text}")

        res_json = response.json()
        if "data" not in res_json or "jobId" not in res_json["data"]:
            raise RuntimeError(f"Format respon API tidak terduga (tidak ada jobId): {res_json}")

        job_id = res_json["data"]["jobId"]
        logger.info(f"Job berhasil dikirim ke PaddleOCR API. Job ID: {job_id}")
        return job_id

    def poll_for_results(self, job_id: str) -> str:
        """
        Melakukan polling ke endpoint status job hingga selesai ('done') atau gagal ('failed').
        Mengembalikan URL file hasil JSONL (jsonUrl).
        """
        if requests is None:
            raise RuntimeError("Library 'requests' belum terinstal.")

        headers = self._prepare_headers()
        start_time = time.time()
        
        logger.info(f"Mulai polling untuk hasil job ID: {job_id}...")

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout_seconds:
                raise TimeoutError(f"Waktu tunggu pemrosesan PaddleOCR-VL melampaui batas ({self.timeout_seconds}s) untuk Job ID {job_id}.")

            response = requests.get(f"{self.job_url}/{job_id}", headers=headers)
            if response.status_code != 200:
                logger.warning(f"Error polling status (HTTP {response.status_code}): {response.text}")
                time.sleep(self.poll_interval)
                continue

            res_json = response.json()
            data = res_json.get("data", {})
            state = data.get("state", "unknown")

            if state == 'pending':
                logger.debug(f"[Job {job_id}] Status: PENDING ({int(elapsed)}s)")
            elif state == 'running':
                progress = data.get('extractProgress', {})
                total_pages = progress.get('totalPages', '?')
                extracted_pages = progress.get('extractedPages', '?')
                logger.debug(f"[Job {job_id}] Status: RUNNING | Halaman diproses: {extracted_pages}/{total_pages} ({int(elapsed)}s)")
            elif state == 'done':
                progress = data.get('extractProgress', {})
                logger.info(f"[Job {job_id}] Status: DONE! Selesai dalam {int(elapsed)}s. Ekstraksi halaman: {progress.get('extractedPages', 1)}")
                result_url = data.get('resultUrl', {}).get('jsonUrl')
                if not result_url:
                    raise RuntimeError(f"Job selesai tetapi tidak menemukan jsonUrl di respon API: {data}")
                return result_url
            elif state == 'failed':
                error_msg = data.get('errorMsg', 'Unknown error')
                logger.error(f"[Job {job_id}] Status: FAILED | Alasan: {error_msg}")
                raise RuntimeError(f"PaddleOCR-VL Job {job_id} gagal diproses: {error_msg}")
            else:
                logger.warning(f"[Job {job_id}] Status tidak dikenal: {state}")

            time.sleep(self.poll_interval)

    def download_and_parse_jsonl(
        self,
        jsonl_url: str,
        save_layout_dir: Optional[str] = None,
        sample_prefix: str = "doc"
    ) -> str:
        """
        Mengunduh hasil JSONL dari URL yang diberikan, mengekstrak teks markdown/layout parsing,
        serta menyimpan dokumen/gambar pendukung jika save_layout_dir ditentukan.
        """
        if requests is None:
            raise RuntimeError("Library 'requests' belum terinstal.")

        logger.info(f"Mengunduh hasil parsing JSONL dari: {jsonl_url}")
        response = requests.get(jsonl_url)
        response.raise_for_status()

        lines = response.text.strip().split('\n')
        if save_layout_dir:
            os.makedirs(save_layout_dir, exist_ok=True)

        extracted_markdown_blocks = []
        page_num = 0

        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                logger.error(f"Gagal memparsing baris ke-{line_num} sebagai JSON: {e}")
                continue

            result = data.get("result", {})
            layout_results = result.get("layoutParsingResults", [])

            # Jika layoutParsingResults kosong, periksa langsung di root result
            if not layout_results and isinstance(result, dict):
                layout_results = [result]
            elif not layout_results and isinstance(data, dict) and "markdown" in data:
                layout_results = [data]

            for i, res in enumerate(layout_results):
                # 1. Coba ambil dari markdown text
                markdown_data = res.get("markdown", {}) if isinstance(res, dict) else {}
                text_md = markdown_data.get("text", "") if isinstance(markdown_data, dict) else ""
                
                # 2. Jika markdown text lemah (misal hanya menangkap 'atoyo J P O' < 25 karakter),
                # periksa seluruh field lain (pruningResult, parsingResult, texts, rec_texts, textLines)
                alternative_texts = []
                if isinstance(res, dict):
                    for key in ("pruningResult", "parsingResult", "texts", "rec_texts", "textLines", "ocrResult", "words"):
                        val = res.get(key)
                        if isinstance(val, str) and len(val.strip()) > len(text_md.strip()):
                            alternative_texts.append(val.strip())
                        elif isinstance(val, list):
                            lines_from_list = []
                            for item in val:
                                if isinstance(item, str) and item.strip():
                                    lines_from_list.append(item.strip())
                                elif isinstance(item, dict):
                                    t = item.get("text") or item.get("rec_text") or item.get("label") or ""
                                    if t and str(t).strip():
                                        lines_from_list.append(str(t).strip())
                            if lines_from_list:
                                joined = "\n".join(lines_from_list)
                                if len(joined) > len(text_md.strip()):
                                    alternative_texts.append(joined)

                # Pilih teks dengan isi alfanumerik & kata terbanyak
                best_page_text = text_md.strip()
                for alt in alternative_texts:
                    if len(alt) > len(best_page_text):
                        best_page_text = alt

                if best_page_text:
                    extracted_markdown_blocks.append(best_page_text)

                # Simpan file markdown atau gambar bila diminta
                if save_layout_dir and isinstance(res, dict):
                    md_filename = os.path.join(save_layout_dir, f"{sample_prefix}_page_{page_num}.md")
                    with open(md_filename, "w", encoding="utf-8") as md_file:
                        md_file.write(best_page_text)
                    logger.debug(f"Markdown dokumen tersimpan di: {md_filename}")

                    # Unduh dan simpan gambar hasil potongan markdown
                    images_dict = markdown_data.get("images", {}) if isinstance(markdown_data, dict) else {}
                    for img_path, img_url in images_dict.items():
                        try:
                            full_img_path = os.path.join(save_layout_dir, img_path)
                            os.makedirs(os.path.dirname(full_img_path), exist_ok=True)
                            img_bytes = requests.get(img_url, timeout=15).content
                            with open(full_img_path, "wb") as img_file:
                                img_file.write(img_bytes)
                        except Exception as e_img:
                            logger.warning(f"Gagal mengunduh gambar potongan {img_url}: {e_img}")

                    # Unduh outputImages layout parsing
                    output_images = res.get("outputImages", {}) if isinstance(res.get("outputImages"), dict) else {}
                    for img_name, img_url in output_images.items():
                        try:
                            img_resp = requests.get(img_url, timeout=15)
                            if img_resp.status_code == 200:
                                filename = os.path.join(save_layout_dir, f"{sample_prefix}_{img_name}_{page_num}.jpg")
                                with open(filename, "wb") as f:
                                    f.write(img_resp.content)
                        except Exception as e_out:
                            logger.warning(f"Gagal mengunduh outputImage {img_url}: {e_out}")

                page_num += 1

        full_extracted_text = "\n\n".join(extracted_markdown_blocks)
        logger.info(f"Berhasil mengekstrak {len(full_extracted_text)} karakter dari {page_num} halaman PaddleOCR-VL.")
        return full_extracted_text

    def extract_text(
        self,
        image_path_or_array: Union[str, Any],
        save_layout_dir: Optional[str] = None,
        sample_prefix: str = "sample"
    ) -> str:
        """
        Pintu gerbang utama (end-to-end): Mengirim job, polling hasil, dan mengembalikan teks OCR/Markdown.
        """
        job_id = self.submit_job(image_path_or_array)
        jsonl_url = self.poll_for_results(job_id)
        text_result = self.download_and_parse_jsonl(
            jsonl_url,
            save_layout_dir=save_layout_dir,
            sample_prefix=sample_prefix
        )
        return text_result


class PaddleOCRLocalProcessor:
    """
    Menangani ekstraksi teks secara lokal di perangkat menggunakan model PaddleOCR PP-OCRv4.
    Dilengkapi dengan pengelompokan baris spasial (spatial line clustering) dan
    parameter sensitivitas tinggi khusus permukaan melengkung/mengkilap (tube kosmetik silver).
    """
    _ocr_instance = None

    @classmethod
    def get_instance(cls):
        if cls._ocr_instance is None:
            logger.info("Initializing PaddleOCR Local (PP-OCRv4) instance dengan sensitivitas tinggi...")
            # Setup environment variables untuk performa stabil di CPU Windows
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
            
            try:
                from paddleocr import PaddleOCR
                cls._ocr_instance = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,      # Matikan doc_unwarping di CPU lokal agar tidak menahan proses hingga 3,5 menit
                    use_textline_orientation=True,
                    det_limit_side_len=960,       # Batasi resolusi deteksi maksimum ke 960px untuk kecepatan eksekusi CPU (<3 detik)
                    text_det_thresh=0.1,          # Turunkan sensitivitas deteksi agar kontras lemah di tube silver tertangkap
                    text_det_box_thresh=0.3,      # Pertahankan kotak bounding box berukuran kecil
                    text_det_unclip_ratio=2.2,    # Perluas rasio unclip agar huruf pinggir tidak terpotong glare
                    lang='en',
                    ocr_version='PP-OCRv4',
                    cpu_threads=4,
                    enable_mkldnn=False
                )
            except Exception as e:
                logger.error(f"Gagal mengimpor/menginisialisasi PaddleOCR Local: {e}")
                raise RuntimeError(f"PaddleOCR Local initialization failed: {e}")
        return cls._ocr_instance

    @staticmethod
    def _sort_boxes_spatially(bounding_boxes: List[Any], y_threshold: int = 15) -> List[str]:
        """
        Mengelompokkan kotak bounding box berdasar posisi baris horizontal (y),
        kemudian mengurutkan dari kiri ke kanan (x). Mengatasi masalah urutan pembacaan
        multi-kolom atau daftar kemasan yang agak miring.
        """
        parsed_items = []
        for item in bounding_boxes:
            if not item or len(item) < 2:
                continue
            poly, text_info = item[0], item[1]
            if not isinstance(text_info, (list, tuple)) or not text_info[0]:
                continue
            
            text = str(text_info[0]).strip()
            if not text:
                continue

            try:
                y_center = sum([pt[1] for pt in poly]) / len(poly)
                x_left = min([pt[0] for pt in poly])
                parsed_items.append({"text": text, "y": y_center, "x": x_left})
            except Exception:
                parsed_items.append({"text": text, "y": 0, "x": 0})

        if not parsed_items:
            return []

        parsed_items.sort(key=lambda k: k["y"])
        lines = []
        current_line = [parsed_items[0]]

        for item in parsed_items[1:]:
            if abs(item["y"] - current_line[0]["y"]) <= y_threshold:
                current_line.append(item)
            else:
                current_line.sort(key=lambda k: k["x"])
                lines.append(" ".join([k["text"] for k in current_line]))
                current_line = [item]

        if current_line:
            current_line.sort(key=lambda k: k["x"])
            lines.append(" ".join([k["text"] for k in current_line]))

        return lines

    def _run_raw_ocr(self, image_input: Any) -> str:
        ocr = self.get_instance()
        lines = []
        
        # 1. Normalkan & Resize jika gambar terlalu besar (>1400px) agar pemrosesan CPU tidak memakan waktu bermenit-menit
        img_to_process = image_input
        if cv2 is not None:
            try:
                if isinstance(image_input, str) and os.path.exists(image_input):
                    img_to_process = cv2.imread(image_input)
                elif isinstance(image_input, np.ndarray):
                    img_to_process = image_input
                
                if isinstance(img_to_process, np.ndarray):
                    h, w = img_to_process.shape[:2]
                    max_dim = max(h, w)
                    if max_dim > 960:
                        scale = 960.0 / max_dim
                        new_w, new_h = int(w * scale), int(h * scale)
                        img_to_process = cv2.resize(img_to_process, (new_w, new_h), interpolation=cv2.INTER_AREA)
                        logger.debug(f"Resized image for fast CPU PaddleOCR: {w}x{h} -> {new_w}x{new_h}")
            except Exception as e_resize:
                logger.debug(f"Resize image info: {e_resize}")
                img_to_process = image_input

        result = ocr.ocr(img_to_process)
        if result and len(result) > 0 and result[0] is not None:
            sorted_lines = self._sort_boxes_spatially(result[0])
            if sorted_lines:
                return "\n".join(sorted_lines)

        if hasattr(ocr, 'predict') and callable(getattr(ocr, 'predict')):
            result_pred = ocr.predict(img_to_process)
            if result_pred:
                for res in result_pred:
                    data = res.json if hasattr(res, 'json') else (res if isinstance(res, dict) else None)
                    if isinstance(data, dict):
                        rec_texts = data.get("rec_texts") or data.get("res", {}).get("rec_texts", [])
                        dt_polys = data.get("dt_polys") or data.get("res", {}).get("dt_polys", [])
                        if rec_texts and dt_polys and len(dt_polys) == len(rec_texts):
                            paired_raw = [[dt_polys[idx], (rec_texts[idx], 1.0)] for idx in range(len(rec_texts))]
                            sorted_lines = self._sort_boxes_spatially(paired_raw)
                            if sorted_lines:
                                return "\n".join(sorted_lines)
                        elif rec_texts:
                            lines.extend([str(t) for t in rec_texts])
        return "\n".join(lines)

    def extract_text(self, image_path_or_array: Union[str, Any]) -> str:
        """
        Menjalankan OCR lokal PP-OCRv4 Murni dengan ukuran gambar teroptimasi untuk kecepatan eksekusi CPU (<3 detik).
        """
        return self._run_raw_ocr(image_path_or_array)
