"""
Authentication middleware for GammaRips MCP Server
Validates API keys and tracks usage for billing
"""

import hashlib
import logging
import os

from google.cloud import firestore

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """Middleware for API key authentication and usage tracking."""

    def __init__(self):
        self.require_api_key = os.getenv("REQUIRE_API_KEY", "false").lower() == "true"
        self.project_id = os.getenv("GCP_PROJECT_ID")

        if self.require_api_key:
            self.db = firestore.Client(project=self.project_id)
            self.users_collection = os.getenv("FIRESTORE_COLLECTION_USERS", "taas_users")
            self.usage_collection = os.getenv("FIRESTORE_COLLECTION_USAGE", "usage_logs")
            logger.info("Authentication middleware enabled")
        else:
            logger.warning("Authentication middleware disabled (REQUIRE_API_KEY=false)")

    def _hash_api_key(self, api_key: str) -> str:
        """Hash an API key for secure storage comparison."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def validate_api_key(self, api_key: str | None) -> dict:
        """Validate an API key and return user information.

        Args:
            api_key: The API key from the request header

        Returns:
            dict: User information if valid

        Raises:
            ValueError: If API key is invalid or user is not authorized
        """
        # Skip validation if authentication is disabled
        if not self.require_api_key:
            return {
                "user_id": "anonymous",
                "email": "anonymous@gammarips.com",
                "plan": "free",
                "subscription_status": "active",
            }

        # Check if API key is provided
        if not api_key:
            raise ValueError("API key is required. Include X-API-Key header in your request.")

        # Hash the provided API key
        api_key_hash = self._hash_api_key(api_key)

        # Query Firestore for the user
        try:
            users_ref = self.db.collection(self.users_collection)
            query = users_ref.where("api_key_hash", "==", api_key_hash).limit(1)
            docs = query.stream()

            user_doc = next(docs, None)

            if not user_doc:
                raise ValueError("Invalid API key")

            user_data = user_doc.to_dict()
            user_data["user_id"] = user_doc.id

            # Check subscription status
            if user_data.get("subscription_status") != "active":
                raise ValueError(
                    f"Subscription is {user_data.get('subscription_status')}. "
                    "Please update your payment information at gammarips.com"
                )

            return user_data

        except StopIteration:
            raise ValueError("Invalid API key")
        except Exception as e:
            logger.error(f"Error validating API key: {e}", exc_info=True)
            raise ValueError("Authentication failed")

    async def track_usage(self, user_id: str, tool_name: str) -> None:
        """Track tool usage for billing and analytics.

        Args:
            user_id: The user's ID
            tool_name: The name of the tool being used
        """
        # Skip tracking if authentication is disabled
        if not self.require_api_key:
            return

        try:
            # Increment usage counter in user document
            user_ref = self.db.collection(self.users_collection).document(user_id)
            user_ref.update(
                {
                    "usage_count": firestore.Increment(1),
                    "last_used_at": firestore.SERVER_TIMESTAMP,
                }
            )

            # Log usage event
            usage_ref = self.db.collection(self.usage_collection)
            usage_ref.add(
                {
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                }
            )

            logger.info(f"Tracked usage: user={user_id}, tool={tool_name}")

        except Exception as e:
            # Don't fail the request if usage tracking fails
            logger.error(f"Error tracking usage: {e}", exc_info=True)


# Global instance
auth_middleware = AuthMiddleware()
