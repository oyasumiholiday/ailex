# An invalid form that models repeatedly write is a measurement

2026-07-13 · Ailex notes #1 · [日本語版](post.html?p=measure-fix-remeasure.ja)

Ailex is a small typed language designed on the assumption that its primary writer is an AI. While building it, we keep running the same experiment: hand a model the one-page language primer, have it write real functions, and score them against hidden tests. This post is about a pattern that showed up twice in those measurements — same shape both times. The conclusion first: **invalid code that models write over and over is not a model error. It is a measurement of a gap in the language.**

## First time: lambda annotations

Early Ailex required type annotations on anonymous function parameters: `fn (acc : Float, x : Float) => acc + x`. It felt like the responsible design choice — explicit types, more safety.

We gave Claude Haiku and Claude Opus the primer and eight functions to write. Haiku got 4/8 on the first attempt, Opus 5/8. And **every single failure had the same cause**: both models wrote `fn (acc, x) => ...` — no annotations — exactly as they would in JavaScript or Python.

The semantics were almost always right. One round of error feedback fixed everything. The models could solve the problems; what they couldn't do was guess my syntax.

So we fixed the language: annotations became optional where the expected type is known from context (inference). Re-measured: **both models 8/8, first attempt, zero repairs.** Cost dropped ~30% too — the repair round-trips vanished.

## Second time: Option and map

Later, after the language grew an `Option[T]` type (typed absence), we expanded the acceptance test to sixteen tasks and measured again. The same shape appeared.

Haiku 15/16, Opus 15/16. The one failure was **the same task, written the same way, by both models**:

```
unwrapOr(map(find(es, fn (e) => e.amount > lim), fn (e) => e.cat), "none")
```

They applied `map` to the result of `find` — an Option — the way Rust's `option.map` or Haskell's `fmap` works. In Ailex at the time, `map` was list-only, so this was a type error. The "correct" solution required peeking into the Option with a dummy sentinel value — an ugly shape.

Here is the interesting part: **given three rounds of type-error feedback, neither model ever produced the "correct" form.** They effectively refused to write the unnatural thing.

We overloaded `map` to work on Option (one function). Re-measured: **both models 16/16.** The expression both models wrote for that task was **character-for-character identical** to the run before — this time it was simply correct.

## The general lesson

| | pass@1 before | Language fix | pass@1 after |
|---|---|---|---|
| Lambda annotations | 50–63% | Made annotations optional (inference) | **100%** |
| map × Option | 94% | Overloaded map for Option | **100%** |

Both times, the thing we fixed was not the model and not the prompt. It was the language. And both times, after the fix, the models' original first attempt — unchanged — became the correct answer.

Human-oriented language design has an option we don't have: educating the writer. Style guides, linters, code review. When the writer is an LLM, its prior — the sense of "natural code" formed by billions of lines of existing programs — is a constant you cannot change from the outside. So measure it, and fit the language to it. It's faster, and it works.

> For an AI-first language, not fighting the model's prior is a first-class design constraint.

## Honest limits

- Each measurement is 16 tasks, one repetition. Small scale.
- The primer changes by a line alongside each language fix, so language effect and teaching-material effect are not fully separated. (We attribute the effect to the language because every failure had a single, identical cause.)
- "Fit the model" is not an absolute rule. We do not follow priors that reduce safety — implicit numeric conversion, for instance. Int and Float still never mix in Ailex without an explicit cast.

## Try it

The language [runs in your browser](../). Every experiment log — including failed hypotheses and retracted claims — is in the [GitHub repository](https://github.com/oyasumiholiday/ailex).
