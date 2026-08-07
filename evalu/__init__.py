"""
evalu — label-free evaluation for the greenwashing Graph-RAG pipeline.

Implements "Khung Đánh giá Toàn diện ... cho Hệ thống Graph-RAG Phát hiện
Greenwashing Không Nhãn":

  §2  component-level intrinsic metrics that need NO ground truth  -> metrics.py
  §3  the 5-point Likert expert rubric + annotation scaffolding    -> rubric.py
  §4  inter-annotator agreement (Fleiss, Krippendorff, Gwet)       -> iaa.py

Nothing here writes to the pipeline's artifacts. Every module reads
graph_output/, data/ and config/ strictly READ-ONLY and emits its own report
under evalu/out/, so an evaluation run can never perturb what it measures.
"""

__all__ = ["iaa", "metrics", "rubric", "loaders", "lexicon", "report"]
