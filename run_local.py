from kaggle_environments import make


def main():
    # יצירת סביבת המשחק
    env = make("orbit_wars", configuration={"seed": 9568547}, debug=True)

    # הרצת המשחק: הסוכן שלנו מול 3 סוכנים רנדומליים (סה"כ 4 שחקנים)
    print("Starting simulation with 4 players...")
    players = ["main.py", "player1.py", "player2.py", "player4.py"]
    steps = env.run(players)

    # הדפסת התוצאות של התור האחרון
    final_step = steps[-1]
    print("\n--- Final Results ---")
    for i, state in enumerate(final_step):
        print(f"Player {i} {players[i]}: reward (score) = {state.reward}, status = {state.status}")

    # --- הקוד החדש ליצירת ה-Replay ---
    print("\nGenerating HTML replay...")
    html_content = env.render(mode="html")

    with open("replay.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    print("Done! File 'replay.html' saved to your project folder.")


if __name__ == "__main__":
    main()