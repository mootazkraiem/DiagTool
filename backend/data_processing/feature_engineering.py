from backend.ml.core.feature_engineering import add_features

class FeatureEngineer:
    @staticmethod
    def build(df):
        return add_features(df)