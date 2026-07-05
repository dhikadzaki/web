# Cara Membuat Chat Bisa Dipakai Publik

App chat ini memakai TCP, jadi alamat publiknya bukan seperti URL web biasa.

Contoh alamat publik dari ngrok:

```text
tcp://0.tcp.ngrok.io:12345
```

Teman kamu nanti isi:

```text
Host: 0.tcp.ngrok.io
Port: 12345
```

## Langkah Simple Pakai Ngrok

1. Jalankan app chat:

```bash
python3 tcpchat_master_gui.py
```

2. Di app, klik:

```text
Start Server
```

3. Install ngrok dari:

```text
https://ngrok.com/download
```

4. Login / daftar akun ngrok.

5. Pasang authtoken dari dashboard ngrok. Contohnya:

```bash
ngrok config add-authtoken TOKEN_KAMU
```

Ganti `TOKEN_KAMU` dengan token asli dari ngrok.

6. Buka terminal baru, jalankan:

```bash
ngrok tcp 5000
```

7. Ngrok akan memberi alamat seperti ini:

```text
Forwarding  tcp://0.tcp.ngrok.io:12345 -> localhost:5000
```

8. Kasih ke teman:

```text
Host: 0.tcp.ngrok.io
Port: 12345
```

9. Teman buka app chat, isi host dan port itu, lalu klik:

```text
Connect
```

## Catatan Penting

- Kamu harus tetap menjalankan server chat di laptop kamu.
- Terminal ngrok harus tetap terbuka.
- Kalau ngrok dimatikan, alamat publiknya mati.
- Kalau pakai ngrok gratis, alamat host/port bisa berubah setiap kali dijalankan ulang.
- Jangan share authtoken ngrok ke orang lain. Kalau token pernah terlihat di screenshot, lebih aman reset token dari dashboard ngrok.

## Kalau Muncul ERR_NGROK_107

Artinya authtoken ngrok salah, expired, atau sudah dicabut.

Cara fix:

1. Buka dashboard ngrok:

```text
https://dashboard.ngrok.com/get-started/your-authtoken
```

2. Copy authtoken yang baru dari dashboard.

3. Jalankan:

```bash
ngrok config add-authtoken TOKEN_BARU_KAMU
```

4. Coba lagi:

```bash
ngrok tcp 5000
```

Kalau masih error, klik reset/regenerate token di dashboard ngrok, lalu ulangi langkah nomor 2 sampai 4.

## Urutan Singkat

```text
Kamu: Start Server
Kamu: ngrok tcp 5000
Teman: Connect ke host dan port dari ngrok
```
