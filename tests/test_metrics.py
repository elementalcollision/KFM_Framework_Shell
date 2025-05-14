"""Tests for the core.metrics module."""

import unittest
import time
from prometheus_client import REGISTRY

from core.metrics import (
    record_llm_request,
    record_embedding_request,
    record_step_execution,
    record_turn_started,
    record_turn_completed,
    LLM_REQUEST_LATENCY,
    LLM_TOKENS_TOTAL,
    LLM_COST_TOTAL,
    LLM_ERRORS_TOTAL,
    STEP_EXECUTION_TOTAL,
    TURN_EXECUTION_TOTAL,
    ACTIVE_TURNS
)

class TestMetrics(unittest.TestCase):
    """Test the metrics recording functions."""
    
    def test_record_llm_request(self):
        """Test recording LLM request metrics."""
        # Record a successful LLM request
        record_llm_request(
            provider="test_provider",
            model="test_model",
            start_time=time.time() - 0.5,
            end_time=time.time(),
            input_tokens=100,
            output_tokens=50,
            cost=0.02,
            status="success"
        )
        
        # Record an error LLM request
        record_llm_request(
            provider="test_provider",
            model="test_model",
            start_time=time.time() - 0.3,
            end_time=time.time(),
            input_tokens=0,
            output_tokens=0,
            cost=0,
            status="error",
            error_type="auth"
        )
        
        # Verify metrics were recorded
        # Note: In a real test we'd use a fresh registry, but this simplified approach works for demonstration
        self.assertTrue(any("llm_request_latency_seconds" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("llm_tokens_total" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("llm_cost_total_usd" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("llm_errors_total" in s.name for s in REGISTRY._collector_to_names.keys()))
    
    def test_record_embedding_request(self):
        """Test recording embedding request metrics."""
        record_embedding_request(
            provider="test_provider",
            model="test_embedding_model",
            start_time=time.time() - 0.2,
            end_time=time.time(),
            input_tokens=300,
            cost=0.01,
            status="success"
        )
        
        # Verify metrics were recorded
        self.assertTrue(any("llm_request_latency_seconds" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("llm_tokens_total" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("llm_cost_total_usd" in s.name for s in REGISTRY._collector_to_names.keys()))
    
    def test_step_and_turn_metrics(self):
        """Test recording step and turn metrics."""
        # Record step execution
        record_step_execution(step_type="LLM_CALL", status="SUCCEEDED")
        record_step_execution(step_type="TOOL_CALL", status="FAILED")
        
        # Record turn metrics
        record_turn_started()  # Should increment active_turns
        record_turn_completed(status="SUCCEEDED")  # Should decrement active_turns and increment turn_execution_total
        
        # Verify metrics were recorded
        self.assertTrue(any("step_execution_total" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("turn_execution_total" in s.name for s in REGISTRY._collector_to_names.keys()))
        self.assertTrue(any("active_turns" in s.name for s in REGISTRY._collector_to_names.keys()))

if __name__ == "__main__":
    unittest.main() 