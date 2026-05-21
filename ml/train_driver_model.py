import os
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_PATH = os.path.join(BASE_DIR, "driver_risk_dataset.csv")
MODEL_PATH = os.path.join(BASE_DIR, "driver_risk_model.pkl")
FEATURES_PATH = os.path.join(BASE_DIR, "driver_risk_features.pkl")
REPORT_PATH = os.path.join(BASE_DIR, "driver_risk_training_report.txt")

TARGET_COLUMN = "risk_level"


def main():
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    df = pd.read_csv(DATASET_PATH)

    if TARGET_COLUMN not in df.columns:
        raise ValueError(f"Missing target column: {TARGET_COLUMN}")

    feature_columns = [column for column in df.columns if column != TARGET_COLUMN]

    X = df[feature_columns]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=y
    )

    model = DecisionTreeClassifier(
        max_depth=5,
        min_samples_leaf=2,
        random_state=42
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    accuracy = accuracy_score(y_test, predictions)
    report = classification_report(y_test, predictions)
    matrix = confusion_matrix(y_test, predictions, labels=["low", "medium", "high"])

    tree_rules = export_text(
        model,
        feature_names=feature_columns
    )

    joblib.dump(model, MODEL_PATH)
    joblib.dump(feature_columns, FEATURES_PATH)

    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        file.write("Driver Risk Model Training Report\n")
        file.write("=================================\n\n")
        file.write(f"Dataset rows: {len(df)}\n")
        file.write(f"Training rows: {len(X_train)}\n")
        file.write(f"Testing rows: {len(X_test)}\n")
        file.write(f"Accuracy: {accuracy:.2f}\n\n")

        file.write("Classification report:\n")
        file.write(report)
        file.write("\n")

        file.write("Confusion matrix labels: low, medium, high\n")
        file.write(str(matrix))
        file.write("\n\n")

        file.write("Learned decision tree rules:\n")
        file.write(tree_rules)

    print("Training completed successfully.")
    print(f"Accuracy: {accuracy:.2f}")
    print(f"Model saved to: {MODEL_PATH}")
    print(f"Features saved to: {FEATURES_PATH}")
    print(f"Report saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
