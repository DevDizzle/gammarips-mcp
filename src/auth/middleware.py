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
            self.users_collection = os.getenv("FIRESTORE_COLLECTION_USERS", "users")
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
        # Determine tier from API key prefix
        tier = "FREE"
        if api_key:
            if api_key.startswith("gr_war_") or api_key.startswith("gr_live_"):
                tier = "WAR_ROOM"
            elif api_key.startswith("gr_edge_"):
                tier = "EDGE"
            elif api_key.startswith("gr_free_"):
                tier = "FREE"

        # Skip validation if authentication is disabled
        if not self.require_api_key:
            return {
                "user_id": "anonymous",
                "email": "anonymous@gammarips.com",
                "plan": "free",
                "tier": tier,  # Pass the determined tier even if auth disabled
                "subscription_status": "active",
            }

        # Check if API key is provided
        if not api_key:
            raise ValueError(
                "API key required. Get your key at https://gammarips.com/developers — "
                "Subscribe for $19/mo and generate your API key in your account dashboard."
            )

        # Hash the provided API key
        api_key_hash = self._hash_api_key(api_key)

        # Query Firestore for the user
        try:
            users_ref = self.db.collection(self.users_collection)
            query = users_ref.where("apiKeyHash", "==", api_key_hash).limit(1)
            docs = query.stream()

            user_doc = next(docs, None)

            if not user_doc:
                # If specifically a free key format but not found, maybe allow? 
                # For now, strict check as per original code.
                raise ValueError(
                    "Invalid API key. Check your key at https://gammarips.com/account — "
                    "If you don't have an account, subscribe at https://gammarips.com/developers"
                )

            user_data = user_doc.to_dict()
            user_data["user_id"] = user_doc.id
            user_data["tier"] = tier

            # Check subscription status (webapp uses isSubscribed boolean)
            is_subscribed = user_data.get("isSubscribed", False)

            # Also check trial period (proUntil timestamp)
            pro_until = user_data.get("proUntil")
            in_trial = False
            if pro_until:
                try:
                    from datetime import datetime
                    # Handle Firestore timestamp or standard datetime
                    if hasattr(pro_until, 'timestamp'):
                        ts = pro_until.timestamp()
                    else:
                        ts = pro_until
                        
                    in_trial = ts > datetime.now().timestamp()
                except Exception:
                    pass

            # If user is supposed to be paid tier but not subscribed/trial, downgrade or block?
            # Spec says "Free tier acts as a funnel".
            # If they have a "gr_edge_" key but no sub, maybe we should block or downgrade.
            # The original code raised ValueError. I will keep that safety.
            if (tier in ["EDGE", "WAR_ROOM"]) and not is_subscribed and not in_trial:
                 raise ValueError(
                    "Subscription required. Your trial has expired or subscription is inactive. "
                    "Reactivate at https://gammarips.com/account — $49/mo for full API access."
                )

            return user_data

        except StopIteration:
            raise ValueError(
                "Invalid API key. Check your key at https://gammarips.com/account — "
                "If you don't have an account, subscribe at https://gammarips.com/developers"
            )
        except Exception as e:
            logger.error(f"Error validating API key: {e}", exc_info=True)
            raise ValueError(
                "Authentication failed. If this persists, contact support@gammarips.com — "
                "New users: subscribe at https://gammarips.com/developers"
            )

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
