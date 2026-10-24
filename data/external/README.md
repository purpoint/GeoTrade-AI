# External benchmark: SEntFiN 1.0

`sentfin-v1-sample.csv` is a fixed sample (seed 42) of 300 single-entity headlines, 100 per label, from SEntFiN 1.0. These are Economic Times headlines from 2011 to 2015. Three MBA students labelled each one, the curator resolved disagreements, and every label is per entity. The labels are independent of this project, so `backend evaluate` uses them to measure how far each scorer agrees with people. Our own golden sets were labelled by the project team.

Source: https://github.com/pyRis/SEntFiN (MIT licence, copied in `SEntFiN-LICENSE`).

> Ankur Sinha, Satishwar Kedas, Rishu Kumar, Pekka Malo. "SEntFiN 1.0: Entity-Aware Sentiment Analysis for Financial News." Journal of the Association for Information Science and Technology, 2022. doi:10.1002/asi.24634. arXiv:2305.12257.
