# ADR 010: Ecology Foundation and Simulation LOD

- **Status**: Accepted
- **Date**: 2026-11-22
- **Applies to**: World Kernel, Environment, Wildlife, Domain Contracts, World Orchestration
- **Baseline**: `refactor/layered-architecture` at `279a33b226599000064b3ad91354d85ad7e7aef0`
- **Purpose**: Establish the next development phase: a standalone, independently evolving ecological world, designed to support multi-resolution simulation.

## 1. Context

The layered architecture phase has established the principal domain boundaries, state ownership, contracts, unified world assembly, deterministic random streams, and scheduler phases. The ecological implementation is not yet a complete ecosystem: vegetation and wildlife still include resource-pool-based mechanisms, and a complete multi-species food web, population dynamics, and nutrient cycle have not yet been implemented.

The next phase must not simply add more ecological features to the existing settlement simulation. It must first align design documents with the current implementation, establish a general simulation-detail policy, and then build and validate ecology without requiring Human Society to run.

This decision defines direction and constraints. It does not claim that the capabilities below already exist, nor does it prescribe premature implementation details.

## 2. Decisions

### 2.1 Phase objective: Ecology Foundation

The phase objective is to establish a complete ecological simulation that:

1. Can be initialized, advanced, observed, replayed, and persisted without Human Society.
2. Models Environment and Wildlife as cooperating but independently state-owning domains.
3. Supports interacting species, population dynamics, energy flow, and nutrient cycling.
4. Uses the existing World Kernel, event log, deterministic random streams, spatial infrastructure, scheduler, and serialization facilities.
5. Is compatible with general multi-resolution simulation (Simulation LOD).
6. Allows Human Society to be reintroduced later through explicit contracts, without transferring ecological state ownership.

Ecology is a general natural-world capability, not a subsystem whose existence depends on agriculture, settlement, or human population.

### 2.2 Simulation LOD is a general World Kernel capability

Simulation LOD (Level of Detail) is a cross-domain simulation mechanism. It belongs to **Infrastructure / World Kernel**, not to Environment, Wildlife, or Human Society.

The Kernel owns the policy and runtime coordination for simulation detail. Domains own their state and implement domain behavior at the requested detail. World Orchestration schedules execution and preserves causal ordering; it must not absorb domain rules or become a second LOD owner.

The LOD mechanism must support:

- **Interest targets**: an entity, species/group, object, or location can be designated as a focus.
- **Spatial influence**: detail can vary with distance and relevance to one or more focus targets; the system must not assume that only a single camera position exists.
- **Multiple detail levels**: at minimum, the architecture must allow fine, normal, and coarse simulation. Exact names, thresholds, and algorithms remain implementation decisions.
- **Budget-aware allocation**: detail selection may account for configured compute budgets and target priority.
- **Continuous world evolution**: coarse simulation is still simulation. It may aggregate entities, use statistical or lower-frequency updates, but must not silently freeze non-focused regions.
- **State continuity**: changing detail must not create or destroy population, biomass, inventory, energy, age, or spatial state merely because a region or entity changed detail level.
- **Determinism**: with the same world configuration, seed, inputs, and LOD policy, execution must be reproducible. Any permitted variation between LOD policies must be explicit and testable.
- **Domain neutrality**: the same Kernel mechanism must be usable by Environment, Wildlife, and future domains; it must not contain ecology-specific assumptions.

LOD changes computational representation and update resolution, not the meaning of domain rules or the conservation constraints those rules enforce. A fine/coarse transition must have an explicit conversion policy and must preserve the invariants defined by the owning domain.

This phase must establish the LOD contract and architectural extension points before ecological subsystems depend on them. A sophisticated adaptive LOD scheduler is not a prerequisite for the first ecological implementation; a simple deterministic policy or uniform-detail mode may be used initially, provided it conforms to the contract and does not block later refinement.

### 2.3 Ecology consists of Environment and Wildlife

The ecological system consists of two peer domains. The food web is a cross-domain ecological relationship, not a third state-owning domain.

**Environment owns and settles:**
- Terrain, climate, hydrology, water bodies, soil, and habitat conditions.
- Wild plants, vegetation communities, and their biomass, growth, reproduction, succession, degradation, and recovery.
- Non-living natural resources.
- Detritus, carcasses, excrement, decomposers (including fungi and bacteria), decomposition, and nutrient return to soil and water.
- Field ecological state, including crop growth and soil/fertility state, regardless of whether the field is used by humans.

**Wildlife owns and settles:**
- Animal individuals and populations, including fish, insects, birds, and terrestrial animals.
- Animal life history, age structure, energy/health state, birth, death, migration, and population changes.
- Animal behavior, including feeding, drinking, movement, reproduction, avoidance, and predation.
- Animal-side outcomes of competition, predation, and feeding.

**Cross-domain ecological relationships:**
- Species definitions and food-web relationships describe possible feeding links among plants, animals, and decomposers.
- Wildlife decides and settles animal behavior and animal population changes.
- Environment validates and settles changes to plants, water, soil, detritus, decomposers, and nutrient pools.
- Cross-domain effects are expressed through contracts, commands, or events; one domain must never directly mutate the other's internal state.
- No shared resource-pool facade may become a second owner of biological state.

The existing resource-pool implementation is a transitional mechanism, not the final definition of a species or population. It may be retained where useful during migration, but new ecological design must not equate a resource pool with a complete biological population model.

### 2.4 Human Society is excluded from the ecological runtime, not removed from the architecture

For this phase, the ecological world profile must be able to run with Environment and Wildlife without registering or invoking Human Society modules.

This is a runtime isolation boundary, not a deletion or rewrite of the Human Society domain:

- Do not delete, disable globally, or relocate Human Society merely to create an ecology-only run.
- Do not make Environment or Wildlife import or require Agent, household, agriculture, governance, construction, or other Society state.
- Do not allow ecological initialization or evolution to depend on human population, settlement, labor, or production.
- Preserve Human Society's independent state ownership and existing implementation.
- Human influence on ecology is out of the ecological core loop. Future human activities must re-enter through explicit query/command/event contracts, with the ecological state owner validating and settling each impact.
- Human activity must not directly write ecological state or bypass ecological rules.

The ecology-only profile must reuse the existing assembly and scheduler infrastructure. It must not introduce a parallel World, clock, event log, spatial graph, random-number system, or replay engine.

### 2.5 Ecological completeness

A complete ecological foundation must represent the following connected processes, rather than a collection of disconnected resource counters:

1. **Primary production**: plants and other producers grow under climate, water, soil, and habitat constraints.
2. **Consumption and predation**: organisms obtain energy from available food through explicit food-web relationships.
3. **Population dynamics**: birth, growth, mortality, predation, competition, migration, and carrying constraints affect populations.
4. **Decomposition**: dead organic matter and excretion enter decomposition processes; decomposers transform material and return nutrients.
5. **Nutrient cycling**: returned nutrients affect environmental pools and can be reused by producers.
6. **Environmental feedback**: organisms affect vegetation, soil, water, and habitats; environmental changes feed back into organism survival and distribution.
7. **Energy and material accounting**: modeled transfers and losses must have explicit accounting boundaries. The system must not create biomass, energy, or nutrients without a declared external input or modelled source.

The initial implementation need not model every species or every biochemical pathway. It must, however, establish extensible mechanisms and demonstrate at least one coherent end-to-end ecological cycle with multiple interacting species and decomposer/nutrient feedback. Simplified models are acceptable when their assumptions and limits are explicit.

### 2.6 Documentation must match implementation

Before broad ecological feature implementation, review the existing design tree and align it with the current repository:

- Keep architecture and cross-cutting Kernel policies distinct from domain system designs.
- Keep Environment, Wildlife, and Human Society designs under their actual domain boundaries.
- Keep cross-domain contracts explicit and separate from state ownership.
- Keep location/scenario configuration distinct from reusable system rules.
- Keep accepted decisions as the authoritative record of architectural choices.
- Mark each capability as implemented, partial, planned, or deprecated; do not describe planned behavior as current behavior.
- Prefer updating or consolidating existing documents over creating parallel or duplicate design trees.
- Do not perform broad directory moves solely for cosmetic consistency. Any path change must reflect a real responsibility correction and update references.

This alignment is a required first work item in the phase. This ADR is the only decision document introduced by this decision; detailed system specifications and implementation plans must be created only when their scope is understood and approved.

## 3. Execution order

Work proceeds in this order:

1. **Architecture and documentation alignment**: audit the current code and design tree; record actual module responsibilities, state ownership, dependencies, contracts, scheduler phases, and known gaps. Correct contradictory or stale descriptions without changing runtime behavior unnecessarily.
2. **LOD foundation**: specify the Kernel-level LOD contract, ownership, policy inputs/outputs, domain adaptation boundary, state-transition invariants, and deterministic test expectations. Do not overbuild adaptive optimization before a working ecological model needs it.
3. **Independent ecological foundation**: create or refine an ecology-only world profile using the existing assembly and scheduler; implement Environment/Wildlife processes and their contracts while Human Society remains outside the runtime.
4. **Validation and integration readiness**: test independent operation, ecological cycles, domain isolation, determinism/replay, and LOD compatibility. Only after the ecology-only boundary is demonstrated should future Human Society integration be planned.

Each step must leave the existing architecture and tests in a coherent state. Preserve the existing long-run population and economic baselines as historical references; do not silently change them to make ecology tests pass.

## 4. Acceptance criteria

The phase is complete only when evidence demonstrates:

- An ecology-only profile initializes and advances without registering or importing Human Society runtime modules.
- Environment and Wildlife have exclusive ownership of their respective states, with no cross-domain direct writes.
- The ecological model includes interacting producers, consumers, predators/competitors as appropriate, decomposers, and nutrient feedback.
- Birth, death, feeding, biomass/material transfers, and environmental feedback are represented by explicit, testable rules.
- The same configuration and seed reproduce the same event stream under the same LOD policy.
- Fine, normal, and coarse detail policies can be represented without freezing coarse regions or violating domain invariants during transitions. If only a uniform or manually assigned policy is implemented initially, the unimplemented adaptive behavior is clearly recorded as deferred.
- Existing Kernel facilities are reused; no parallel simulation infrastructure is introduced.
- Human Society remains intact and can later interact through contracts without acquiring ecological state ownership.
- Documentation accurately distinguishes current implementation, this phase's deliverables, and deferred work.

## 5. Explicit non-goals

This decision does not authorize:

- A rewrite of Human Society or a redesign of its population, marriage, household, agriculture, or economy mechanics.
- Deleting Human Society modules or permanently removing human impact from the world model.
- Implementing every known species, a fully realistic biosphere, or detailed biochemical simulation in one phase.
- Building a separate ecology engine, clock, event stream, spatial system, scheduler, or replay mechanism.
- Treating LOD as a visual-only camera feature or allowing coarse regions to stop evolving.
- Changing unrelated historical simulation parameters or weakening existing tests and assertions.
- Broad code migration before the documentation and architecture audit identifies a concrete need.

## 6. Consequences

- Environment and Wildlife become the independently runnable ecological core; Human Society remains a separate, temporarily unregistered domain in the ecology-only profile.
- The Kernel gains a domain-neutral extension point for simulation detail, while each domain remains responsible for its own state and rules.
- Existing resource pools can coexist temporarily with richer biological models, but must not become permanent substitutes for species and population dynamics.
- Ecological implementation is staged behind explicit ownership, contracts, and validation, reducing the risk of coupling natural processes to settlement mechanics.
- The phase may expose existing boundary violations or missing contracts. Such findings must be recorded and resolved at the owning layer rather than bypassed with cross-domain state access.
