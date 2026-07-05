import tkinter as tk


def main():
    window = tk.Tk()
    window.title("Hello World GUI")
    window.geometry("320x180")
    window.resizable(False, False)

    container = tk.Frame(window, padx=24, pady=24)
    container.pack(expand=True, fill="both")

    label = tk.Label(
        container,
        text="Hello World",
        font=("Arial", 22, "bold"),
    )
    label.pack(expand=True)

    close_button = tk.Button(
        container,
        text="Tutup",
        command=window.destroy,
        width=12,
    )
    close_button.pack()

    window.mainloop()


if __name__ == "__main__":
    main()
