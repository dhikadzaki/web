# God Chat Qt C++

Ini adalah client chat C++/Qt untuk server Python `tcpchat_master_gui.py`.

## Cara coba di laptop

1. Jalankan server Python:

   ```bash
   python3 tcpchat_master_gui.py
   ```

2. Klik `Start Server`. Host server sudah default `0.0.0.0`, jadi teman di Wi-Fi yang sama bisa connect.

3. Cari IP laptop server:

   ```bash
   hostname -I
   ```

4. Build client Qt C++:

   ```bash
   cmake -S god_chat_qt_cpp -B god_chat_qt_cpp/build
   cmake --build god_chat_qt_cpp/build
   ```

5. Jalankan app, isi IP laptop server, port `5000`, username, lalu connect.

## Build APK Android

Untuk APK, install:

- Qt 6.5 atau lebih baru
- Qt for Android
- Android Studio
- Android SDK
- Android NDK
- JDK

Lalu buka folder `god_chat_qt_cpp` di Qt Creator, pilih kit `Android`, kemudian tekan `Build APK`.

Catatan: file ini adalah source project APK. Build APK final butuh toolchain Android di komputermu.
