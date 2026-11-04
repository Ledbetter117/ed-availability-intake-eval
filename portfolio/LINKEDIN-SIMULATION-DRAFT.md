# LinkedIn draft — simulation edition

I built a small, reproducible test of a practical question: can a vision model preserve the dates, availability marks and notes on a calendar?

The new simulation uses 12 fictional calendars and 36 images. Each calendar appears in three matched conditions: typed text, a licensed handwriting font, and a degraded version of that same handwriting image. The dates include months with 28, 29, 30 and 31 days. A visible legend distinguishes a blank mark from availability.

The plan and synthetic reference answers were frozen before model calls. The comparison unit is the calendar, and failed or incomplete responses stay in the results. The code also checks for the error that matters most to this task: turning an unavailable day into an available one.

The completed local-model simulation collected 36/36 first observations. Strict exact-calendar recovery was 4/12 typed, 3/12 handwriting-font, and 3/12 degraded-handwriting calendars.

This is a simulation, not a validation study of human handwriting or real staff scheduling. Fonts and image transformations are useful controlled tests, but they do not reproduce a person's writing or intent. The original human-study work remains separate.

The repository includes the images, synthetic answers, scoring code, font licenses, tests, report and numerical provenance. The software and writing were developed with AI assistance; software test controls are kept separate from actual model observations.

Code and report: https://github.com/Ledbetter117/ed-availability-intake-eval

Draft only. No post has been sent.
