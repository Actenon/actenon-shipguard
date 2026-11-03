# Output-flood probe correction after engine freeze

Run 41709493832 at documentation-only commit 7228de6 failed the output-flood test;
all other five jobs passed. The same frozen engine had passed all six jobs in
41708530409. No holdout BDE execution had occurred.

Ten raw local repetitions reproduced the cause once: `writeSync` stopped on
`EAGAIN: resource temporarily unavailable, write` after 99,019 stdout bytes,
below the 100,000-byte test cap. The runner refused the polluted JSON output.
The other nine repetitions reached the external output cap as expected.

The negative probe now retries only EAGAIN with a one-millisecond wait, continuing
the flood until the cap kills execution. The assertion still requires the explicit
`output exceeded` error and zero findings. No production or discovery code changed;
engine commit 137a680 and the preregistered holdout remain frozen. This is a test
fixture correction, not a relaxation to accept any environment failure.
