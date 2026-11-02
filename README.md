# Dashboard Strategi Balap F1

Dashboard race strategist: rencana Plan A/B/C sebelum race, rekomendasi box, kompon, dan energi saat race, lalu tinjauan keputusan setelah race. Dasar produknya [PRD](PRD%20—%20Dashboard%20Strategi%20Balap%20F1.pdf) yang sudah dievaluasi dan diperbaiki di [docs/evaluasi-prd.md](docs/evaluasi-prd.md).

**Semua data di aplikasi ini simulasi.** Belum ada feed telemetri atau timing tim yang terhubung, dan performa model belum teruji pada race nyata. Jangan dipakai untuk keputusan sungguhan.

## Menjalankan

Butuh Python 3.11+ dan Node 20+.

```powershell
# sekali saja
pip install -r backend/requirements.txt
cd frontend; npm install; npm run build; cd ..

# jalankan
cd backend
python -m uvicorn f1strat.api:app --host 127.0.0.1 --port 8000
```

Buka <http://127.0.0.1:8000>.

Untuk mengembangkan frontend, jalankan server di atas lalu `npm run dev` di `frontend/`, dan buka <http://localhost:5173>.

## Cara pakai

1. **Pra-Race.** Pilih sirkuit, tim, dan skenario latihan, lalu tekan *Jalankan simulasi* (sekitar 25 detik). Hanya peran Chief of Strategy yang bisa mengunci plan.
2. **Race.** Tekan *Mulai race*. Mobil hanya pit bila Anda memutuskannya, jadi perhatikan kartu rekomendasi.
3. **Pasca-Race.** Terbuka otomatis saat bendera finis: replay gapper, rapor model, dan keputusan dibanding alternatifnya.

*Kontrol latihan* mengatur kecepatan simulasi dan menyuntikkan kejadian: Safety Car, VSC, bendera merah, hujan, sayap rusak, feed putus, model gagal.

| Tombol | Aksi |
| --- | --- |
| `1` `2` | Pilih mobil |
| `B` | Box sesuai rekomendasi |
| `S` | Tetap di lintasan, atau batalkan panggilan box |
| `G` `W` `L` | Gapper, What-if, Log keputusan |

## Struktur

```
backend/f1strat/
  catalog.py       sirkuit, tim, skenario
  laptime.py       model lap time
  montecarlo.py    simulator seluruh grid
  strategy.py      Plan A/B/C, playbook, jendela pit, undercut, cuaca
  estimators.py    degradasi (Bayesian), peluang pit lawan, saran energi
  recommender.py   kartu rekomendasi dan what-if
  session.py       orkestrasi live, keputusan, peran, jejak audit
  world.py         feed simulasi, satu-satunya sumber data saat ini
  scorecard.py     pengukuran terhadap target PRD
  api.py           REST dan WebSocket
frontend/src/      React: views/ untuk tiga mode, components/ untuk panel
```

Jejak audit tiap sesi tersimpan di `backend/data/sessions/<id>.jsonl`.

## Menguji

```powershell
cd backend
python -m pytest tests -q                       # sekitar 1 menit
python -m f1strat.scorecard --races 12          # akurasi terhadap target PRD
python -m f1strat.scorecard --compare --races 8 # ikut rekomendasi vs ikut plan
```

Saat mengukur kecepatan, tutup dulu browser lain yang membuka aplikasi. Peta yang terbuka di browser headless tanpa GPU memakan satu core penuh dan bisa membuat hitung ulang terlihat beberapa kali lebih lambat.

## Menghubungkan data sungguhan

`RaceWorld.frame()` adalah satu-satunya pintu data. Adapter feed resmi cukup menghasilkan bentuk frame yang sama (`timing`, `telemetry`, `race_control`, `weather`), lalu menggantikan `RaceWorld` di `RaceSession`. Dua hal yang wajib dibuang saat itu:

- Metode `radio_*` di `world.py`. Di simulasi metode itu mewakili pembalap yang mendengar radio. Sistem sungguhan tidak punya kanal ke mobil.
- `fp_report()` dan `truth()`. Keduanya membaca nilai tersembunyi simulator.

Peran saat ini hanya dipilih di layar dan dikirim lewat header `X-Role`. Itu pembatas alur kerja, bukan keamanan. Autentikasi sungguhan dan enkripsi dari PRD belum dibuat.
