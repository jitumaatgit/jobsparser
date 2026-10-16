/* Self-grading multiple-choice quiz.
 *
 * Usage in a lesson:
 *   <div class="quiz" data-correct="b" data-yes="Nice recall." data-no="Not quite — <why>.">
 *     <div class="q">Question text?</div>
 *     <button class="quiz-opt" data-key="a"><span class="quiz-key">a</span>Answer a</button>
 *     <button class="quiz-opt" data-key="b"><span class="quiz-key">b</span>Answer b</button>
 *     <div class="quiz-feedback" aria-live="polite"></div>
 *   </div>
 * Attempts to keep the DOM leaky-but-fair: correct answer lives in data-correct.
 * Include with <script src="../assets/quiz.js" defer></script>.
 */
(function () {
  function grade(quiz, picked) {
    if (quiz.dataset.answered) return;
    quiz.dataset.answered = "1";
    var correct = quiz.dataset.correct;
    var ok = picked === correct;
    quiz.querySelectorAll(".quiz-opt").forEach(function (btn) {
      btn.disabled = true;
      if (btn.dataset.key === correct) btn.classList.add("correct");
      else if (btn.dataset.key === picked) btn.classList.add("incorrect");
    });
    var fb = quiz.querySelector(".quiz-feedback");
    fb.textContent = ok ? (quiz.dataset.yes || "Correct.") : (quiz.dataset.no || "Not quite.");
    fb.classList.add("show", ok ? "ok" : "no");
  }

  document.querySelectorAll(".quiz").forEach(function (quiz) {
    quiz.querySelectorAll(".quiz-opt").forEach(function (btn) {
      btn.addEventListener("click", function () { grade(quiz, btn.dataset.key); });
    });
  });
})();
