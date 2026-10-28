package local.sleepsounds.controller

import org.junit.Assert.*
import org.junit.Test

class ConnectionPolicyTest {
    @Test fun offlinePreferredHostNeverFallsBackToAnotherHost(){
        assertEquals("preferred",HostSelection.automatic("preferred",listOf("other" to "id-other")))
        assertEquals("preferred",HostSelection.automatic("preferred",emptyList()))
    }
    @Test fun oneHostAtTwoAddressesDoesNotRequirePicker(){
        assertEquals("lan",HostSelection.automatic(null,listOf("lan" to "same-id","mesh" to "same-id")))
        assertNull(HostSelection.automatic(null,listOf("a" to "id-a","b" to "id-b")))
        assertNull(HostSelection.automatic(null,emptyList()))
    }
    @Test fun retriesShareTheOriginalDeadline(){
        val budget=ConnectionBudget(1000)
        assertFalse(budget.expired(20_999));assertTrue(budget.expired(21_000))
        assertEquals(500,budget.timeout(20_500));assertEquals(0L,budget.remaining(22_000))
        assertEquals(1500,budget.timeout(1000))
    }
}
