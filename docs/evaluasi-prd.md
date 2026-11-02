# Evaluasi dan perbaikan PRD Dashboard Strategi Balap F1

Mengevaluasi PRD tertanggal 11 Oktober 2026. Dokumen ini berlaku sebagai addendum v1.1: tiap perbaikan di bawah menjadi requirement dan sudah diterapkan di aplikasi, kecuali yang ditandai lain.

## Kesimpulan

PRD ini kuat di visi, prinsip UX, dan batasan regulasi. Prinsip "dashboard memberi rekomendasi, strategist yang memutuskan" serta pemisahan data pasti dan estimasi sudah tepat dan dipertahankan.

Yang perlu diperbaiki sebelum dilanjutkan ada lima: gerbang go-live tidak bisa dilewati secara logika, PRD merancang untuk satu mobil padahal tim punya dua, Plan A/B/C terputus dari Mode Race, tenggat keputusan SC yang sebenarnya tidak terdefinisi, dan angka regulasi energi sudah usang karena perubahan FIA di tengah musim.

## Temuan kritis

Temuan ini membuat produk tidak bisa dirilis atau mengambil keputusan yang salah bila tidak diperbaiki.

| ID | Masalah di PRD | Perbaikan |
| --- | --- | --- |
| K1 | **Gerbang 3 mustahil dilewati.** Syaratnya "target di bagian Tujuan tercapai di shadow mode", padahal dua target hanya terukur setelah live: "100% setelah 3 GP live" dan "keputusan lebih baik". | Pisahkan metrik gerbang (terukur saat shadow) dari metrik pasca go-live. |
| K2 | **Hanya satu mobil.** Tim punya dua mobil, tetapi layar hanya punya satu kartu rekomendasi dan satu panel mobil. Tidak ada double stack maupun fungsi tujuan tim. | Rekomendasi per mobil dengan pindah satu tombol. Optimizer memaksimalkan poin tim. Double stack dimodelkan (antre sekitar 4 dtk) dan diberi peringatan. |
| K3 | **Plan terputus dari race.** Mode Pra-Race menghasilkan pemicu, tetapi tidak ada fitur Mode Race yang memantaunya. | Baris plan aktif, pemantau pemicu otomatis, dan alert dengan tombol pindah plan. |
| K4 | **Tenggat SC yang keliru.** Target "< 3 detik" hanya mengukur waktu hitung. Tenggat sebenarnya adalah saat mobil melewati pintu pit, dikurangi waktu radio. | Playbook menjawab seketika, Monte Carlo menyusul. Kartu menampilkan hitung mundur ke pintu pit dengan margin radio 4 dtk. |
| K5 | **Angka energi usang.** Lihat bagian koreksi regulasi. | Model energi memakai batas per sirkuit dan kapasitas 4 MJ. Dokumen Power Unit Information FIA menjadi sumber data per event. |

## Temuan penting

Temuan ini membuat hasil menyesatkan atau metrik tidak bisa dipercaya.

| ID | Masalah di PRD | Perbaikan |
| --- | --- | --- |
| T1 | **Akhir pekan sprint tidak disebut.** Alur kerja mengandaikan FP1 sampai FP3, padahal enam akhir pekan 2026 hanya punya satu sesi latihan sebelum kompetisi. | Prior degradasi 1,7× lebih lebar pada akhir pekan sprint, dan ini ditampilkan di layar. |
| T2 | **Estimasi degradasi lawan terkontaminasi energi.** PRD hanya mengoreksi bahan bakar dan lalu lintas. Di 2026, lawan yang menabung energi terlihat seperti bannya turun. | Lap lawan diberi bobot lebih rendah, dan keyakinannya dibatasi paling tinggi "sedang". |
| T3 | **Presisi tanpa recall.** Target "≥ 70% presisi" bisa dicapai dengan nyaris tidak pernah memprediksi. Mobil pit di sekitar 5% jendela lap. | Laporkan presisi dan recall bersama. Target awal juga perlu ditinjau, lihat hasil pengukuran. |
| T4 | **Posisi keluar pit tidak memisahkan kondisi.** Saat SC, siapa yang ikut pit memang acak, sehingga ± 1 posisi tidak realistis. | Dua target: ± 1 pada ≥ 90% pit kondisi hijau, dan posisi aktual di dalam rentang tampil pada ≥ 80% pit saat netralisasi. |
| T5 | **"Keyakinan" tidak terdefinisi.** PRD memakai persen dan label tanpa arti. | Keyakinan adalah peluang aksi terpilih mengalahkan alternatif terbaik dalam race simulasi yang sama (common random numbers). |
| T6 | **Metrik "keputusan lebih baik" tanpa definisi.** | Bandingkan race yang mengikuti rekomendasi dengan race yang mengikuti plan pada seed yang sama. |
| T7 | **Failover dan data basi tanpa angka.** | Ambang basi: telemetri 2 dtk, timing dan race control 3 dtk, cuaca 60 dtk. Bila model gagal, data mentah tetap tampil. Angka failover server masih perlu ditetapkan. |
| T8 | **Replay ada di lingkup tanpa fitur**, padahal Gerbang 2 bergantung padanya. | Mode ketiga: Pasca-Race, berisi replay, rapor model, dan keputusan dibanding alternatif. |
| T9 | **Tidak ada cara membangun sebelum feed tersedia.** Akses feed masih pertanyaan terbuka. | Feed simulasi dengan kontrak data yang sama, plus mode latihan untuk menyuntikkan kejadian. |
| T10 | **Formula lap time kurang lengkap.** Tidak ada warm-up, evolusi lintasan, dan kondisi basah. Aturan khusus event seperti batas panjang stint juga belum ada. | Warm-up, evolusi, dan basah ditambahkan. Δtraffic dan Δenergi dihitung per mobil. Batas stint khusus event belum dibuat. |

## Temuan sedang

| ID | Masalah di PRD | Perbaikan |
| --- | --- | --- |
| S1 | Tabel peran sudah menjawab siapa yang mengunci plan, tetapi masih menjadi pertanyaan terbuka. | Chief of Strategy, ditegakkan di server. |
| S2 | Lingkup menyebut playbook bendera merah, tetapi fiturnya hanya SC/VSC. | Bendera merah masuk playbook. |
| S3 | Keterangan gambar menyebut 7 panel, diagramnya 8. | Diterapkan 8 panel. |
| S4 | "Hanya kartu rekomendasi berwarna aksen" bertabrakan dengan merah, kuning, dan warna kompon. | Warna aksen hanya di kartu. Merah dan kuning khusus status. Warna kompon khusus ban. |
| S5 | Peran punya kebutuhan tanpa fitur: catatan race engineer, kalibrasi tyre engineer. | Keduanya dibuat. Kalibrasi baru tersedia lewat API, belum ada layarnya. |
| S6 | Analis rival di remote ops baru ada di fase 4, tetapi tag kerusakan dibutuhkan saat shadow. | Tag tersedia sejak awal dan dicocokkan dengan kehilangan waktu. |
| S7 | "Kebiasaan tim" mengandaikan riwayat, padahal Cadillac tim baru. | Kartu lawan menandai tim tanpa riwayat. |
| S8 | Stack terlalu berat untuk MVP. | Lihat keputusan teknis. |
| S9 | Pertanyaan terbuka tanpa pemilik dan tenggat, dan akses feed adalah penghalang utama. | Lihat bagian akhir. "mobil tik" tampaknya salah ketik "mobil tim". |

## Koreksi regulasi

| PRD | Kondisi sebenarnya | Sumber |
| --- | --- | --- |
| Panen sekitar 8,5 MJ per lap | Berbeda per event. Silverstone 2026: race 8,0 MJ, atau 8,5 MJ saat Overtake aktif. Kualifikasi 6,5 MJ. | FIA PU Information British GP |
| State of charge tanpa kapasitas | Maksimal 4 MJ energi terpakai pada satu waktu. | ESPN |
| Boost memberi tenaga penuh | Sejak Miami, Boost race dibatasi +150 kW, atau daya saat aktivasi bila lebih tinggi. | FIA |
| MGU-K hingga 350 kW | 350 kW di zona akselerasi utama, 250 kW di bagian lain lap. | FIA |
| Super clipping | Daya puncak naik ke 350 kW, juga berlaku saat race. | FIA |
| Titik deteksi "umumnya tikungan terakhir" | Ditetapkan per event. Silverstone: gap 1,0 dtk, garis deteksi 5560 m (saat itu TBC). | FIA PU Information British GP |
| Pertanyaan terbuka soal aturan kompon | Dua kompon kering wajib di race kering. 13 set kering per akhir pekan, 12 di sprint. Perlu dicek ulang ke Sporting Regulations, sumbernya sekunder. | Mercedes, ringkasan media |

Nilai Silverstone di aplikasi diambil dari dokumen FIA. Nilai recharge Monza dan Spa adalah asumsi.

## Keputusan teknis

| PRD mengusulkan | Keputusan untuk MVP | Alasan |
| --- | --- | --- |
| Inti simulator Rust/C++ bila perlu | NumPy saja | 1.500 race penuh untuk satu mobil selesai sekitar 0,4 dtk di laptop. |
| Grafik WebGL | Canvas dan SVG | Hanya 22 mobil dan sekitar 1.100 titik data. |
| Kafka, ClickHouse, BigQuery | Bus di dalam proses dan log JSONL | Belum ada feed untuk diproses. Batas adapter sudah disiapkan. |
| FastAPI, WebSocket, React | Dipakai sesuai PRD | |

Font di-host sendiri karena jaringan pit wall terpisah dari internet.

## Tambahan dari proses build

Empat requirement ini muncul dari bug nyata saat pengujian.

- **Uji kebijakan wajib ada di Gerbang 2.** Bug terparah adalah opsi "box sekarang" yang diam-diam disimulasikan sebagai tidak pernah pit. Semua tes unit tetap hijau. Bug itu baru terlihat dari hasil race yang tidak masuk akal.
- **Hasil model harus bisa kedaluwarsa.** Simulasi yang selesai setelah mobil pit pernah memicu pit kedua. Hasil untuk mobil yang kondisinya sudah berubah kini dibuang.
- **Perubahan rencana harus punya keunggulan berarti.** Selisih utilitas di bawah 0,15 adalah noise simulasi, sedangkan pit stop adalah ongkos nyata. Tanpa ambang ini sistem terlalu sering menyuruh pit.
- **Tenggat hitung dijaga oleh anggaran, bukan harapan.** Bila hitung ulang melewati 1,5 dtk, jumlah race diturunkan otomatis (minimal 60 per opsi) dan naik lagi saat longgar. Kartu memberi peringatan bila hitung ulang lambat atau kartunya sudah lama.

## Hasil pengukuran

Semua angka berasal dari race simulasi. Model dan simulator berbagi struktur, jadi angka ini adalah batas atas dan membuktikan alurnya bekerja, bukan akurasinya di race nyata.

| Target | Hasil | Target PRD atau perbaikan | Status |
| --- | --- | --- | --- |
| Error degradasi mobil sendiri, setelah 5 lap | 0,027 dtk/lap | < 0,15 | Lolos |
| Hitung ulang p95, browser terbuka | 0,76 dtk | < 3 dtk | Lolos |
| Hitung ulang saat Safety Car | 0,59 dtk | < 3 dtk | Lolos |
| Latensi server ke layar, mesin yang sama | 9 sampai 17 ms | < 500 ms | Lolos, tetapi belum mencakup feed sungguhan |
| Posisi keluar pit kondisi hijau, dalam 1 posisi | 85% | ≥ 90% | Belum lolos |
| Posisi keluar pit saat SC/VSC, di dalam rentang tampil | 74% | ≥ 80% | Belum lolos |
| Presisi prediksi pit lawan, 2 lap | 49% | ≥ 70% | Belum lolos |
| Recall prediksi pit lawan | 11% | Belum ada target, usulan ≥ 40% | Belum lolos |

Akurasi diukur pada 12 race (352 pit stop dan 11.235 prediksi pit lawan). Kecepatan diukur pada satu race penuh.

Target presisi 70% perlu ditinjau ulang. Di simulator, waktu pit lawan bervariasi sekitar ± 3 lap, sehingga jendela 2 lap sulit diprediksi hanya dari umur ban. Opsinya: perlebar jendela menjadi 3 lap, atau tambah sinyal lain seperti kru yang bersiap di pit lane. Nilai model ini sebaiknya diukur dari kalibrasi peluangnya, bukan satu ambang.

**Uji kebijakan.** Dua kebijakan dijalankan pada 12 seed yang sama:

| Kebijakan | Poin tim per race | Posisi rata-rata | Stop rata-rata | Stop terbanyak |
| --- | --- | --- | --- | --- |
| Ikut plan pra-race saja | 3,83 | 10,7 | 1,54 | 2 |
| Ikut rekomendasi live | 7,50 | 8,8 | 1,67 | 3 |

Rekomendasi lebih baik di 8 race, sama di 3, dan lebih buruk di 1. Selisih rata-rata +3,7 poin (galat baku 1,6), mediannya +1 poin. Pembandingnya lemah karena plan saja tidak bereaksi terhadap Safety Car, jadi hasil ini menunjukkan rekomendasi bekerja dan tidak merusak race, bukan besarnya keunggulan terhadap strategist manusia.

## Status implementasi

**Sudah jalan:** Mode Pra-Race, Race, dan Pasca-Race. Simulator seluruh grid, model degradasi Bayesian, prediksi posisi keluar pit, kalkulator undercut dan overcut, panel energi, kartu lawan, playbook, skenario cuaca, what-if, gapper, log keputusan, brief pra-race, alert, tema siang dan malam, pintasan keyboard, jejak audit, batas peran di server.

**Belum dibuat:**

- Koneksi feed sungguhan. Semua data masih simulasi.
- Autentikasi dan enkripsi. Peran saat ini hanya pembatas alur kerja.
- Server cadangan dan failover.
- Penalti waktu, batas stint khusus event, dan efek mobil yang dilapisi.
- Layar kalibrasi tyre engineer.

Tidak ada model yang teruji pada data race nyata.

## Pertanyaan terbuka

| Pertanyaan | Mengapa penting | Usulan pemilik |
| --- | --- | --- |
| Format dan akses feed timing/GPS resmi | Penghalang utama Discovery | Kepala data |
| Telemetri sendiri tersedia dalam format apa | Syarat target 500 ms | Kepala data |
| Apakah ada simulator atau model ban yang harus diintegrasikan | Menentukan kerja fase MVP | Chief of Strategy |
| Dashboard di pit wall, remote ops, atau keduanya | Menentukan arsitektur tag analis | Chief of Strategy |
| Verifikasi aturan kompon dan alokasi ke Sporting Regulations terbaru | Sumber saat ini sekunder | Tyre engineer |
| Target failover: berapa detik beralih, berapa data boleh hilang | Belum ada angka | Kepala infrastruktur |

## Sumber

- [FIA: refinements to the 2026 regulations](https://api.fia.com/news/refinements-2026-fia-formula-1-regulations-agreed-all-stakeholders)
- [FIA: 2026 British Grand Prix, Power Unit Information](https://www.fia.com/system/files/decision-document/2026_british_grand_prix_-_power_unit_information.pdf)
- [ESPN: F1's 2026 rule tweaks explained](https://www.espn.com/f1/story/_/id/48548710/explained-f1-2026-rule-tweaks-changed-impact-difference-driver-criticism-max-verstappen)
- [Formula 1: format Sprint 2026](https://www.formula1.com/en/latest/article/how-does-the-f1-sprint-race-format-work-in-2026.3PyLPAazrBNe8kQIS3wOfY.3PyLPAazrBNe8kQIS3wOfY)
- [Mercedes: opsi ban GP Australia 2026](https://www.mercedesamgf1.com/news/what-are-the-tyre-options-for-the-2026-australian-gp)
- [The Race: late Japanese GP rule change](https://www.the-race.com/formula-1/late-japanese-gp-f1-2026-rule-change-qualifying-energy-saving-fears.md)
