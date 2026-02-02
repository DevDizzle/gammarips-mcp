# GammaRips Roadmap

## Immediate Next Steps
- [ ] **API Setup:** Configure `google.generativeai` with valid API keys in the production environment.
- [ ] **LLM Evaluation:** Run the `tests/comprehensive_runner.py` in the configured environment to generate valid "LLM-as-a-Judge" quality scores for all tools.
- [ ] **Integration Tests:** Add end-to-end integration tests connecting to the deployed Cloud Run instance.

## Future Enhancements
- [ ] **User Authentication:** Implement proper user auth (Phase 2).
- [ ] **Real-time Alerts:** Add WebSocket or SSE push for real-time options signals.
- [ ] **Frontend Dashboard:** Build a React/Next.js frontend to visualize the MCP data.
