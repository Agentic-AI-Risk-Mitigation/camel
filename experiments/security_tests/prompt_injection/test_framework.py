"""Test framework for running prompt injection attacks against CaMeL agents."""

import sys
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add project root to path (parent of experiments)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import get_logger

logger = get_logger("security_tests")


class AttackResult:
    """Result of a single attack test."""
    
    def __init__(
        self,
        test_id: str,
        agent_name: str,
        attack_type: str,
        payload: str,
        success: bool,
        blocked_by: Optional[str] = None,
        error_message: Optional[str] = None,
        response: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        self.test_id = test_id
        self.agent_name = agent_name
        self.attack_type = attack_type
        self.payload = payload
        self.success = success  # True = attack succeeded (bad), False = blocked (good)
        self.blocked_by = blocked_by  # Which security mechanism blocked it
        self.error_message = error_message
        self.response = response
        self.metadata = metadata or {}
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/reporting."""
        return {
            "test_id": self.test_id,
            "agent_name": self.agent_name,
            "attack_type": self.attack_type,
            "payload": self.payload[:200],  # Truncate for logging
            "success": self.success,
            "blocked_by": self.blocked_by,
            "error_message": self.error_message,
            "response": self.response[:200] if self.response else None,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


class AttackTestSuite:
    """Test suite for running attacks against agents."""
    
    def __init__(self, output_dir: Optional[Path] = None):
        self.results: List[AttackResult] = []
        self.output_dir = output_dir or Path(__file__).parent.parent.parent / "logs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def run_test(
        self,
        test_id: str,
        agent_name: str,
        attack_type: str,
        payload: str,
        execute_fn: callable,
        success_indicators: List[str],
        failure_indicators: List[str]
    ) -> AttackResult:
        """
        Run a single attack test.
        
        Args:
            test_id: Unique test identifier
            agent_name: Name of agent being tested
            attack_type: Type of attack (direct, indirect, etc.)
            payload: Attack payload
            execute_fn: Function to execute the attack (returns response string)
            success_indicators: Strings that indicate attack succeeded
            failure_indicators: Strings that indicate attack was blocked
        
        Returns:
            AttackResult with test outcome
        """
        logger.log_event("test_started", {
            "test_id": test_id,
            "agent": agent_name,
            "attack_type": attack_type
        })
        
        try:
            # Execute the attack
            response = execute_fn(payload)
            
            # Analyze response
            success = False
            blocked_by = None
            
            # Check for success indicators (bad - attack worked)
            for indicator in success_indicators:
                if indicator.lower() in response.lower():
                    success = True
                    break
            
            # Check for failure indicators (good - attack blocked)
            for indicator in failure_indicators:
                if indicator.lower() in response.lower():
                    blocked_by = "security_policy" if "security" in indicator.lower() else "camel_framework"
                    success = False
                    break
            
            result = AttackResult(
                test_id=test_id,
                agent_name=agent_name,
                attack_type=attack_type,
                payload=payload,
                success=success,
                blocked_by=blocked_by,
                response=response
            )
            
        except Exception as e:
            # Exception during execution - likely blocked or error
            error_str = str(e)
            blocked_by = "exception"
            
            if "security policy" in error_str.lower() or "denied" in error_str.lower():
                blocked_by = "security_policy"
            elif "capability" in error_str.lower():
                blocked_by = "capability_system"
            
            result = AttackResult(
                test_id=test_id,
                agent_name=agent_name,
                attack_type=attack_type,
                payload=payload,
                success=False,  # Exception means attack failed
                blocked_by=blocked_by,
                error_message=error_str
            )
        
        self.results.append(result)
        
        # Log result
        logger.log_injection_attempt(
            attack_type=attack_type,
            payload=payload,
            success=result.success,
            details=result.to_dict()
        )
        
        return result
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate summary report of all tests."""
        total_tests = len(self.results)
        successful_attacks = sum(1 for r in self.results if r.success)
        blocked_attacks = total_tests - successful_attacks
        
        # Group by agent
        by_agent = {}
        for result in self.results:
            if result.agent_name not in by_agent:
                by_agent[result.agent_name] = {
                    "total": 0,
                    "successful_attacks": 0,
                    "blocked_attacks": 0,
                    "by_type": {}
                }
            
            by_agent[result.agent_name]["total"] += 1
            if result.success:
                by_agent[result.agent_name]["successful_attacks"] += 1
            else:
                by_agent[result.agent_name]["blocked_attacks"] += 1
            
            # By attack type
            attack_type = result.attack_type
            if attack_type not in by_agent[result.agent_name]["by_type"]:
                by_agent[result.agent_name]["by_type"][attack_type] = {
                    "total": 0,
                    "successful": 0,
                    "blocked": 0
                }
            
            by_agent[result.agent_name]["by_type"][attack_type]["total"] += 1
            if result.success:
                by_agent[result.agent_name]["by_type"][attack_type]["successful"] += 1
            else:
                by_agent[result.agent_name]["by_type"][attack_type]["blocked"] += 1
        
        report = {
            "summary": {
                "total_tests": total_tests,
                "successful_attacks": successful_attacks,
                "blocked_attacks": blocked_attacks,
                "success_rate": f"{(blocked_attacks/total_tests*100):.1f}%" if total_tests > 0 else "N/A"
            },
            "by_agent": by_agent,
            "all_results": [r.to_dict() for r in self.results]
        }
        
        return report
    
    def save_report(self, filename: Optional[str] = None):
        """Save report to file."""
        if filename is None:
            filename = f"attack_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        report = self.generate_report()
        report_path = self.output_dir / filename
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\nReport saved to: {report_path}")
        return report_path
    
    def print_summary(self):
        """Print summary to console."""
        report = self.generate_report()
        
        print("\n" + "="*70)
        print("ATTACK TEST SUMMARY")
        print("="*70)
        
        summary = report["summary"]
        print(f"\nTotal Tests: {summary['total_tests']}")
        print(f"Successful Attacks (BAD): {summary['successful_attacks']}")
        print(f"Blocked Attacks (GOOD): {summary['blocked_attacks']}")
        print(f"Defense Success Rate: {summary['success_rate']}")
        
        print("\n" + "-"*70)
        print("BY AGENT:")
        print("-"*70)
        
        for agent_name, stats in report["by_agent"].items():
            print(f"\n{agent_name}:")
            print(f"  Total: {stats['total']}")
            print(f"  Blocked: {stats['blocked_attacks']} | Failed: {stats['successful_attacks']}")
            
            print("  By Attack Type:")
            for attack_type, type_stats in stats["by_type"].items():
                print(f"    {attack_type}: {type_stats['blocked']}/{type_stats['total']} blocked")
        
        print("\n" + "="*70)
        
        # Highlight any successful attacks
        if summary["successful_attacks"] > 0:
            print("\n[WARNING] Some attacks succeeded!")
            print("Successful attacks:")
            for result in self.results:
                if result.success:
                    print(f"  - {result.test_id}: {result.payload[:100]}")
        else:
            print("\n[SUCCESS] All attacks successfully blocked by CaMeL!")
