"""
Group-aware, stratified train/test split.

Groups near-duplicate jobs by (normalised_title, company) so they always
land on the same side of the split. Stratifies on group-level majority label.
"""
import pandas as pd
from sklearn.model_selection import train_test_split


def make_split(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42):
    """
    Args:
        df: must have columns — id, text, seniority, normalised_title, company_name
    Returns:
        X_train, X_test, y_train, y_test  (all indexed by original df index)
    """
    # 1. Assign each row a group key
    df = df.copy()
    df['group'] = (
        df['normalised_title'].fillna('') + '||' + df['company_name'].fillna('')
    )

    # 2. One label per group — majority vote (ties broken by first occurrence)
    group_label = (
        df.groupby('group')['seniority']
        .agg(lambda s: s.value_counts().index[0])
    )
    df['group_label'] = df['group'].map(group_label)

    # 3. Split at group level, stratified on group label
    groups = group_label.reset_index()  # columns: group, seniority
    train_groups, test_groups = train_test_split(
        groups['group'],
        test_size=test_size,
        stratify=groups['seniority'],
        random_state=random_state,
    )

    train_mask = df['group'].isin(train_groups)
    test_mask  = df['group'].isin(test_groups)

    return (
        df.loc[train_mask, 'text'],
        df.loc[test_mask,  'text'],
        df.loc[train_mask, 'seniority'],
        df.loc[test_mask,  'seniority'],
    )


def check_leakage(df: pd.DataFrame, X_train, X_test) -> None:
    """
    Confirm no near-duplicate pair straddles the split.
    Prints a warning for every group that appears on both sides.
    """
    df = df.copy()
    df['group'] = (
        df['normalised_title'].fillna('') + '||' + df['company_name'].fillna('')
    )
    df['split'] = df.index.map(
        lambda i: 'train' if i in X_train.index else 'test'
    )

    straddling = (
        df.groupby('group')['split']
        .nunique()
        .pipe(lambda s: s[s > 1])
    )

    if straddling.empty:
        print("✓ No near-duplicate pair straddles the split.")
    else:
        print(f"✗ {len(straddling)} group(s) straddle the split:")
        print(straddling.index.tolist())
