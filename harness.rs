use criterion::{black_box, BatchSize, Criterion};
use sds_under_test::*;
use std::collections::BTreeMap;
use std::time::Duration;
use std::sync::Arc;

struct Case {
    name: &'static str,
    rules: Vec<RootRuleConfig<Arc<dyn RuleConfig>>>,
    input: SimpleEvent,
    output: SimpleEvent,
    expected: Vec<(usize, Path<'static>, usize, usize)>,
}
fn text(value: &str) -> SimpleEvent { SimpleEvent::String(value.into()) }
fn map() -> SimpleEvent {
    SimpleEvent::Map(BTreeMap::from([("secret".into(), text("secret")), ("other".into(), text("secret"))]))
}
fn path(value: &str) -> Path<'static> { Path::from(vec![PathSegment::Field(value.to_string().into())]) }
fn rule() -> RootRuleConfig<Arc<dyn RuleConfig>> { RootRuleConfig::new(RegexRuleConfig::new("secret").build()) }
fn cases() -> Vec<Case> {
    let empty = Path::from(vec![]);
    let mut cases = Vec::new();
    for (name, size) in [("small_no_match", 1024), ("large_no_match", 131072)] {
        let input = text(&"x".repeat(size));
        cases.push(Case {name, rules: vec![rule()], output: input.clone(), input, expected: vec![]});
    }
    let input = text(&"secret ".repeat(128));
    cases.push(Case {name: "dense_matches", rules: vec![rule()], output: input.clone(), input,
        expected: (0..128).map(|i| (0, empty.clone(), i*7, i*7+6)).collect()});
    let keyword_rule = || RootRuleConfig::new(RegexRuleConfig::new("secret")
        .with_proximity_keywords(ProximityKeywordsConfig {look_ahead_character_count: 30,
            included_keywords: vec!["password".into()], excluded_keywords: vec![]}).build());
    cases.push(Case {name: "text_keywords", rules: vec![keyword_rule()], input: text("password secret"), output: text("password secret"), expected: vec![(0, empty.clone(), 9, 15)]});
    let input = SimpleEvent::Map(BTreeMap::from([("password".into(), text("secret")), ("other".into(), text("secret"))]));
    cases.push(Case {name: "path_keywords", rules: vec![keyword_rule()], output: input.clone(), input, expected: vec![(0,path("password"),0,6)]});
    cases.push(Case {name: "included_scope", rules: vec![rule().scope(Scope::include(vec![path("secret")]))], input: map(), output: map(), expected: vec![(0,path("secret"),0,6)]});
    // Distinct values isolate path exclusion from SDS's value-based multipass suppression.
    let scoped_input = SimpleEvent::Map(BTreeMap::from([("secret".into(), text("secretA")), ("other".into(), text("secretB"))]));
    cases.push(Case {name: "excluded_scope", rules: vec![RootRuleConfig::new(RegexRuleConfig::new("secret[AB]").build()).scope(Scope::exclude(vec![path("other")]))], output: scoped_input.clone(), input: scoped_input, expected: vec![(0,path("secret"),0,7)]});
    cases.push(Case {name: "redaction", rules: vec![rule().match_action(MatchAction::Redact {replacement: "[REDACTED]".into()})], input: text("secret"), output: text("[REDACTED]"), expected: vec![(0,empty.clone(),0,10)]});
    let rules = (0..64).map(|i| RootRuleConfig::new(RegexRuleConfig::new(&format!("marker{i:03}")).build())).collect();
    let input = text(&"x".repeat(16384));
    cases.push(Case {name: "many_rules", rules, output: input.clone(), input, expected: vec![]});
    cases
}
fn main() {
    let cases = cases();
    // Correctness is checked before Criterion can time any workload.
    for case in &cases {
        let scanner = Scanner::builder(&case.rules).build().unwrap();
        let mut event = case.input.clone();
        let found = scanner.scan(&mut event).unwrap();
        let mut actual: Vec<_> = found.into_iter().map(|m| (m.rule_index, m.path, m.start_index, m.end_index_exclusive)).collect();
        actual.sort();
        let mut expected = case.expected.clone(); expected.sort();
        assert_eq!(actual, expected, "{}: match locations differ", case.name);
        assert_eq!(event, case.output, "{}: mutated event differs", case.name);
    }
    if std::env::var_os("SDS_INVESTIGATOR_VALIDATE").is_some() { return; }
    let mut criterion = Criterion::default().sample_size(30).warm_up_time(Duration::from_millis(500))
        .measurement_time(Duration::from_secs(1)).without_plots().configure_from_args();
    for case in cases {
        let scanner = Scanner::builder(&case.rules).build().unwrap();
        criterion.bench_function(case.name, |b| b.iter_batched(|| case.input.clone(), |mut event| {
            black_box(scanner.scan(black_box(&mut event)).unwrap());
            black_box(event);
        }, BatchSize::SmallInput));
    }
    criterion.final_summary();
}
