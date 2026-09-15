"""
Flip Card Study App — Full Version
------------------------------------
A desktop flashcard app for active recall study, built with Tkinter
(no extra installs needed — just Python 3).

Features:
- Multiple topics/decks
- Add / edit / delete cards
- Click-to-flip study mode (question on front, answer on back)
- Spaced repetition (Leitner system, 5 boxes) so cards you struggle
  with come back sooner, and cards you know well come back later
- "Due today" queue so you always study what actually needs review
- Stats screen: per-topic mastery, streak, totals
- Everything autosaves to flashcards_data.json next to this script

Run it with:  python flashcards_full.py
"""

import json
import os
import random
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, timedelta, datetime

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flashcards_data.json")

# Leitner box -> days until next review when answered correctly
BOX_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}
MAX_BOX = 5


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def today_str():
    return date.today().isoformat()


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for c in data.get("cards", []):
                c.setdefault("box", 1)
                c.setdefault("next_review", today_str())
                c.setdefault("correct", 0)
                c.setdefault("incorrect", 0)
            return data
    return {"cards": [], "next_id": 1, "streak": 0, "last_study_date": None}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class FlashcardApp(tk.Tk):
    FRONT_BG = "#3b82f6"
    BACK_BG = "#10b981"
    BG = "#f3f4f6"

    def __init__(self):
        super().__init__()
        self.title("Flip Card Study App")
        self.geometry("720x560")
        self.configure(bg=self.BG)
        self.minsize(600, 480)

        self.data = load_data()

        self.study_queue = []
        self.current_index = 0
        self.showing_answer = False
        self.session_correct = 0
        self.session_total = 0

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.study_tab = ttk.Frame(notebook)
        self.manage_tab = ttk.Frame(notebook)
        self.add_tab = ttk.Frame(notebook)
        self.stats_tab = ttk.Frame(notebook)

        notebook.add(self.study_tab, text="  Study  ")
        notebook.add(self.manage_tab, text="  Manage Cards  ")
        notebook.add(self.add_tab, text="  Add Card  ")
        notebook.add(self.stats_tab, text="  Stats  ")

        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.build_study_tab()
        self.build_manage_tab()
        self.build_add_tab()
        self.build_stats_tab()

        self.refresh_topic_dropdown()
        self.refresh_manage_list()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def topics(self):
        return sorted(set(c["topic"] for c in self.data["cards"]))

    def cards_due(self, topic=None):
        t = today_str()
        cards = self.data["cards"]
        if topic and topic != "All topics":
            cards = [c for c in cards if c["topic"] == topic]
        return [c for c in cards if c["next_review"] <= t]

    def on_tab_changed(self, event):
        tab_text = self.notebook.tab(self.notebook.select(), "text").strip()
        if tab_text == "Manage Cards":
            self.refresh_manage_list()
        elif tab_text == "Stats":
            self.refresh_stats()
        elif tab_text == "Study":
            self.refresh_topic_dropdown()

    # ------------------------------------------------------------------
    # STUDY TAB
    # ------------------------------------------------------------------

    def build_study_tab(self):
        top = ttk.Frame(self.study_tab)
        top.pack(fill="x", pady=(10, 5), padx=10)

        ttk.Label(top, text="Topic:").pack(side="left")
        self.topic_var = tk.StringVar(value="All topics")
        self.topic_dropdown = ttk.Combobox(top, textvariable=self.topic_var, state="readonly", width=25)
        self.topic_dropdown.pack(side="left", padx=6)

        ttk.Button(top, text="Start Session", command=self.start_session).pack(side="left", padx=6)

        self.due_label = ttk.Label(top, text="")
        self.due_label.pack(side="right")

        # Card canvas
        card_frame = tk.Frame(self.study_tab, bg=self.BG)
        card_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.card_canvas = tk.Canvas(card_frame, bg=self.FRONT_BG, highlightthickness=0)
        self.card_canvas.pack(fill="both", expand=True)
        self.card_canvas.bind("<Button-1>", lambda e: self.flip_card())

        self.card_text_id = self.card_canvas.create_text(
            20, 20, text="Add some cards, then hit Start Session!",
            fill="white", font=("Helvetica", 16, "bold"),
            width=600, anchor="nw"
        )
        self.card_hint_id = self.card_canvas.create_text(
            20, 20, text="", fill="white", font=("Helvetica", 10, "italic"), anchor="sw"
        )
        self.card_canvas.bind("<Configure>", self._reposition_hint)

        # Controls
        controls = ttk.Frame(self.study_tab)
        controls.pack(fill="x", padx=10, pady=(0, 10))

        self.progress_label = ttk.Label(controls, text="")
        self.progress_label.pack(side="left")

        btns = ttk.Frame(controls)
        btns.pack(side="right")

        self.correct_btn = ttk.Button(btns, text="✅ I got it right", command=lambda: self.grade_card(True))
        self.incorrect_btn = ttk.Button(btns, text="❌ I got it wrong", command=lambda: self.grade_card(False))
        self.flip_btn = ttk.Button(btns, text="🔄 Flip card", command=self.flip_card)

        self.flip_btn.pack(side="left", padx=4)
        self.correct_btn.pack(side="left", padx=4)
        self.incorrect_btn.pack(side="left", padx=4)
        self._set_grade_buttons_state("disabled")

    def _reposition_hint(self, event=None):
        w = self.card_canvas.winfo_width()
        h = self.card_canvas.winfo_height()
        self.card_canvas.coords(self.card_hint_id, 20, h - 15)
        self.card_canvas.itemconfig(self.card_text_id, width=max(w - 40, 100))
        self.card_canvas.coords(self.card_text_id, 20, 20)

    def refresh_topic_dropdown(self):
        values = ["All topics"] + self.topics()
        self.topic_dropdown["values"] = values
        if self.topic_var.get() not in values:
            self.topic_var.set("All topics")
        due_count = len(self.cards_due(self.topic_var.get()))
        total_count = len(self.data["cards"] if self.topic_var.get() == "All topics"
                           else [c for c in self.data["cards"] if c["topic"] == self.topic_var.get()])
        self.due_label.config(text=f"{due_count} due today / {total_count} total")

    def start_session(self):
        topic = self.topic_var.get()
        due = self.cards_due(topic)
        if not due:
            messagebox.showinfo("All caught up!", "No cards are due for review right now.\nAdd more cards or check back later.")
            return
        random.shuffle(due)
        self.study_queue = due
        self.current_index = 0
        self.session_correct = 0
        self.session_total = 0
        self.show_current_card()

    def show_current_card(self):
        if self.current_index >= len(self.study_queue):
            self.card_canvas.config(bg=self.FRONT_BG)
            self.card_canvas.itemconfig(
                self.card_text_id,
                text=f"Session complete! 🎉\n\n{self.session_correct}/{self.session_total} correct"
                if self.session_total else "Session complete!"
            )
            self.card_canvas.itemconfig(self.card_hint_id, text="Click Start Session to study more.")
            self._set_grade_buttons_state("disabled")
            self.progress_label.config(text="")
            self.refresh_topic_dropdown()
            self.refresh_stats()
            return

        card = self.study_queue[self.current_index]
        self.showing_answer = False
        self.card_canvas.config(bg=self.FRONT_BG)
        self.card_canvas.itemconfig(self.card_text_id, text=f"[{card['topic']}]\n\n{card['question']}")
        self.card_canvas.itemconfig(self.card_hint_id, text="Click the card (or Flip) to reveal the answer")
        self.progress_label.config(
            text=f"Card {self.current_index + 1} of {len(self.study_queue)}  |  Box {card['box']}/{MAX_BOX}"
        )
        self._set_grade_buttons_state("disabled")

    def flip_card(self):
        if not self.study_queue or self.current_index >= len(self.study_queue):
            return
        card = self.study_queue[self.current_index]
        self.showing_answer = not self.showing_answer
        if self.showing_answer:
            self.card_canvas.config(bg=self.BACK_BG)
            self.card_canvas.itemconfig(self.card_text_id, text=f"[{card['topic']}]\n\n{card['answer']}")
            self.card_canvas.itemconfig(self.card_hint_id, text="How did you do?")
            self._set_grade_buttons_state("normal")
        else:
            self.card_canvas.config(bg=self.FRONT_BG)
            self.card_canvas.itemconfig(self.card_text_id, text=f"[{card['topic']}]\n\n{card['question']}")
            self.card_canvas.itemconfig(self.card_hint_id, text="Click the card (or Flip) to reveal the answer")
            self._set_grade_buttons_state("disabled")

    def _set_grade_buttons_state(self, state):
        self.correct_btn.config(state=state)
        self.incorrect_btn.config(state=state)

    def grade_card(self, correct):
        card = self.study_queue[self.current_index]
        if correct:
            card["box"] = min(card["box"] + 1, MAX_BOX)
            card["correct"] += 1
            self.session_correct += 1
        else:
            card["box"] = 1
            card["incorrect"] += 1

        days = BOX_INTERVALS[card["box"]]
        card["next_review"] = (date.today() + timedelta(days=days)).isoformat()
        self.session_total += 1

        self._update_streak()
        save_data(self.data)

        self.current_index += 1
        self.show_current_card()

    def _update_streak(self):
        last = self.data.get("last_study_date")
        t = today_str()
        if last == t:
            return
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last == yesterday:
            self.data["streak"] = self.data.get("streak", 0) + 1
        else:
            self.data["streak"] = 1
        self.data["last_study_date"] = t

    # ------------------------------------------------------------------
    # MANAGE TAB
    # ------------------------------------------------------------------

    def build_manage_tab(self):
        top = ttk.Frame(self.manage_tab)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Label(top, text="Filter by topic:").pack(side="left")
        self.manage_topic_var = tk.StringVar(value="All topics")
        self.manage_topic_dropdown = ttk.Combobox(top, textvariable=self.manage_topic_var, state="readonly", width=25)
        self.manage_topic_dropdown.pack(side="left", padx=6)
        self.manage_topic_dropdown.bind("<<ComboboxSelected>>", lambda e: self.refresh_manage_list())
        ttk.Button(top, text="Delete Selected", command=self.delete_selected_card).pack(side="right")
        ttk.Button(top, text="Edit Selected", command=self.edit_selected_card).pack(side="right", padx=6)

        columns = ("topic", "question", "answer", "box")
        self.tree = ttk.Treeview(self.manage_tab, columns=columns, show="headings", height=16)
        for col, label, width in [("topic", "Topic", 120), ("question", "Question", 240),
                                   ("answer", "Answer", 240), ("box", "Box", 50)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def refresh_manage_list(self):
        values = ["All topics"] + self.topics()
        self.manage_topic_dropdown["values"] = values
        if self.manage_topic_var.get() not in values:
            self.manage_topic_var.set("All topics")

        for row in self.tree.get_children():
            self.tree.delete(row)

        topic = self.manage_topic_var.get()
        cards = self.data["cards"]
        if topic != "All topics":
            cards = [c for c in cards if c["topic"] == topic]

        for c in cards:
            self.tree.insert("", "end", iid=str(c["id"]),
                              values=(c["topic"], c["question"], c["answer"], c["box"]))

    def _selected_card(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select a card first.")
            return None
        card_id = int(sel[0])
        return next((c for c in self.data["cards"] if c["id"] == card_id), None)

    def delete_selected_card(self):
        card = self._selected_card()
        if not card:
            return
        if messagebox.askyesno("Delete card", f"Delete this card?\n\n{card['question']}"):
            self.data["cards"].remove(card)
            save_data(self.data)
            self.refresh_manage_list()
            self.refresh_topic_dropdown()
            self.refresh_stats()

    def edit_selected_card(self):
        card = self._selected_card()
        if not card:
            return
        self.open_edit_dialog(card)

    def open_edit_dialog(self, card):
        win = tk.Toplevel(self)
        win.title("Edit Card")
        win.geometry("420x300")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="Topic:").pack(anchor="w", padx=10, pady=(10, 0))
        topic_entry = ttk.Entry(win)
        topic_entry.insert(0, card["topic"])
        topic_entry.pack(fill="x", padx=10)

        ttk.Label(win, text="Question:").pack(anchor="w", padx=10, pady=(10, 0))
        q_text = tk.Text(win, height=4)
        q_text.insert("1.0", card["question"])
        q_text.pack(fill="x", padx=10)

        ttk.Label(win, text="Answer:").pack(anchor="w", padx=10, pady=(10, 0))
        a_text = tk.Text(win, height=4)
        a_text.insert("1.0", card["answer"])
        a_text.pack(fill="x", padx=10)

        def save_and_close():
            topic = topic_entry.get().strip() or "General"
            question = q_text.get("1.0", "end").strip()
            answer = a_text.get("1.0", "end").strip()
            if not question or not answer:
                messagebox.showerror("Missing info", "Question and answer can't be empty.")
                return
            card["topic"], card["question"], card["answer"] = topic, question, answer
            save_data(self.data)
            self.refresh_manage_list()
            self.refresh_topic_dropdown()
            self.refresh_stats()
            win.destroy()

        ttk.Button(win, text="Save Changes", command=save_and_close).pack(pady=12)

    # ------------------------------------------------------------------
    # ADD TAB
    # ------------------------------------------------------------------

    def build_add_tab(self):
        frame = ttk.Frame(self.add_tab)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(frame, text="Topic:", font=("Helvetica", 11, "bold")).pack(anchor="w")
        self.new_topic_entry = ttk.Entry(frame)
        self.new_topic_entry.pack(fill="x", pady=(2, 12))

        ttk.Label(frame, text="Question (front of card):", font=("Helvetica", 11, "bold")).pack(anchor="w")
        self.new_question_text = tk.Text(frame, height=5)
        self.new_question_text.pack(fill="x", pady=(2, 12))

        ttk.Label(frame, text="Answer (back of card):", font=("Helvetica", 11, "bold")).pack(anchor="w")
        self.new_answer_text = tk.Text(frame, height=5)
        self.new_answer_text.pack(fill="x", pady=(2, 12))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=8)
        ttk.Button(btn_row, text="Add Card", command=self.add_new_card).pack(side="left")
        self.add_status_label = ttk.Label(btn_row, text="")
        self.add_status_label.pack(side="left", padx=12)

    def add_new_card(self):
        topic = self.new_topic_entry.get().strip() or "General"
        question = self.new_question_text.get("1.0", "end").strip()
        answer = self.new_answer_text.get("1.0", "end").strip()

        if not question or not answer:
            messagebox.showerror("Missing info", "Please fill in both the question and the answer.")
            return

        card = {
            "id": self.data["next_id"],
            "topic": topic,
            "question": question,
            "answer": answer,
            "box": 1,
            "next_review": today_str(),
            "correct": 0,
            "incorrect": 0,
        }
        self.data["cards"].append(card)
        self.data["next_id"] += 1
        save_data(self.data)

        self.new_topic_entry.delete(0, "end")
        self.new_question_text.delete("1.0", "end")
        self.new_answer_text.delete("1.0", "end")
        self.add_status_label.config(text="✔ Card added!")
        self.after(1500, lambda: self.add_status_label.config(text=""))

        self.refresh_topic_dropdown()
        self.refresh_manage_list()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # STATS TAB
    # ------------------------------------------------------------------

    def build_stats_tab(self):
        self.stats_frame = ttk.Frame(self.stats_tab)
        self.stats_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def refresh_stats(self):
        for widget in self.stats_frame.winfo_children():
            widget.destroy()

        cards = self.data["cards"]
        total = len(cards)
        streak = self.data.get("streak", 0)

        header = ttk.Label(self.stats_frame, text="Your Study Stats", font=("Helvetica", 16, "bold"))
        header.pack(anchor="w", pady=(0, 10))

        summary = ttk.Label(
            self.stats_frame,
            text=f"Total cards: {total}    |    Current streak: {streak} day(s)    |    Due today: {len(self.cards_due())}",
            font=("Helvetica", 11)
        )
        summary.pack(anchor="w", pady=(0, 16))

        if not cards:
            ttk.Label(self.stats_frame, text="Add some cards to see stats here.").pack(anchor="w")
            return

        columns = ("topic", "count", "mastered", "avg_box")
        tree = ttk.Treeview(self.stats_frame, columns=columns, show="headings", height=10)
        tree.heading("topic", text="Topic")
        tree.heading("count", text="Cards")
        tree.heading("mastered", text="Mastered (Box 5)")
        tree.heading("avg_box", text="Avg. Box")
        tree.column("topic", width=200)
        tree.column("count", width=100, anchor="center")
        tree.column("mastered", width=140, anchor="center")
        tree.column("avg_box", width=100, anchor="center")
        tree.pack(fill="both", expand=True)

        for topic in self.topics():
            topic_cards = [c for c in cards if c["topic"] == topic]
            mastered = sum(1 for c in topic_cards if c["box"] == MAX_BOX)
            avg_box = sum(c["box"] for c in topic_cards) / len(topic_cards)
            tree.insert("", "end", values=(topic, len(topic_cards), mastered, f"{avg_box:.1f}"))


if __name__ == "__main__":
    app = FlashcardApp()
    app.mainloop()

