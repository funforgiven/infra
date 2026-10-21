// Pointer-selection behavior adapted from the MIT-licensed legacy-v4 snapshot
// a48885b9fec485c903c955749a7da6e30147cd38; see THIRD_PARTY_NOTICES.md.

function text(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value).trim();
}

function folded(value) {
    return text(value).toLowerCase();
}

function compareFolded(left, right) {
    if (left < right) {
        return -1;
    }
    if (left > right) {
        return 1;
    }
    return 0;
}

function textList(value) {
    if (value === null || value === undefined) {
        return [];
    }
    var values = Array.isArray(value) ? value : [value];
    return values.map(text).filter(function (item) {
        return item.length > 0;
    });
}

function normalizeApplication(application) {
    application = application && typeof application === "object" ? application : {};
    var id = text(application.id || application.desktopId);
    if (id.length === 0) {
        return null;
    }

    return {
        id: id,
        name: text(application.name) || id,
        genericName: text(application.genericName),
        comment: text(application.comment),
        keywords: textList(application.keywords),
        iconPath: text(application.iconPath)
    };
}

// Normalises, deduplicates, and case-folds the application list once so each
// query only has to fold itself. Rebuild it when the application list changes.
function prepareApplications(applications) {
    applications = Array.isArray(applications) ? applications : [];
    var seen = Object.create(null);
    var entries = [];

    for (var index = 0; index < applications.length; index += 1) {
        var application = normalizeApplication(applications[index]);
        if (application === null || seen[application.id]) {
            continue;
        }
        seen[application.id] = true;

        var name = application.name.toLowerCase();
        var genericName = application.genericName.toLowerCase();
        var id = application.id.toLowerCase();
        var keywords = application.keywords.join(" ").toLowerCase();
        entries.push({
            application: application,
            name: name,
            genericName: genericName,
            id: id,
            words: name.split(/[\s._-]+/),
            haystack: [name, genericName, id, application.comment.toLowerCase(), keywords].join(" ")
        });
    }
    return {
        entries: entries
    };
}

function subsequenceScore(haystack, needle) {
    if (needle.length === 0) {
        return 0;
    }

    var cursor = -1;
    var gaps = 0;
    for (var index = 0; index < needle.length; index += 1) {
        var next = haystack.indexOf(needle[index], cursor + 1);
        if (next < 0) {
            return -1;
        }
        gaps += next - cursor - 1;
        cursor = next;
    }
    return gaps;
}

function prepareQuery(query) {
    var foldedQuery = folded(query);
    return {
        text: foldedQuery,
        tokens: foldedQuery.split(/\s+/).filter(function (token) {
            return token.length > 0;
        }),
        compact: foldedQuery.replace(/\s+/g, "")
    };
}

function entryScore(entry, query) {
    if (query.text.length === 0) {
        return 0;
    }

    if (entry.name === query.text) {
        return 0;
    }
    if (entry.id === query.text) {
        return 1;
    }
    if (entry.name.indexOf(query.text) === 0) {
        return 10;
    }

    for (var wordIndex = 0; wordIndex < entry.words.length; wordIndex += 1) {
        if (entry.words[wordIndex].indexOf(query.text) === 0) {
            return 20 + wordIndex;
        }
    }

    var tokenScore = 0;
    for (var tokenIndex = 0; tokenIndex < query.tokens.length; tokenIndex += 1) {
        var tokenPosition = entry.haystack.indexOf(query.tokens[tokenIndex]);
        if (tokenPosition < 0) {
            tokenScore = -1;
            break;
        }
        tokenScore += tokenPosition;
    }
    if (tokenScore >= 0) {
        return 40 + tokenScore;
    }

    var fuzzyScores = [
        subsequenceScore(entry.name, query.compact),
        subsequenceScore(entry.genericName, query.compact),
        subsequenceScore(entry.id, query.compact)
    ].filter(function (score) {
        return score >= 0;
    });
    if (fuzzyScores.length === 0) {
        return null;
    }
    return 100 + Math.min.apply(Math, fuzzyScores);
}

// Accepts either a raw application list or the result of prepareApplications.
function filterApplications(applications, query, limit) {
    var prepared = applications && Array.isArray(applications.entries)
        ? applications
        : prepareApplications(applications);
    var foldedQuery = prepareQuery(query);
    var ranked = [];

    for (var index = 0; index < prepared.entries.length; index += 1) {
        var entry = prepared.entries[index];
        var score = entryScore(entry, foldedQuery);
        if (score !== null) {
            ranked.push({
                entry: entry,
                score: score
            });
        }
    }

    ranked.sort(function (left, right) {
        if (left.score !== right.score) {
            return left.score - right.score;
        }
        return compareFolded(left.entry.name, right.entry.name)
            || compareFolded(left.entry.id, right.entry.id);
    });

    var result = ranked.map(function (rankedEntry) {
        return rankedEntry.entry.application;
    });
    var boundedLimit = Number(limit);
    return Number.isSafeInteger(boundedLimit) && boundedLimit > 0
        ? result.slice(0, boundedLimit)
        : result;
}

function moveSelection(currentIndex, delta, count) {
    count = Number(count);
    delta = Number(delta);
    if (!Number.isSafeInteger(count) || count <= 0 || !Number.isSafeInteger(delta)) {
        return -1;
    }

    currentIndex = Number(currentIndex);
    if (!Number.isSafeInteger(currentIndex) || currentIndex < 0 || currentIndex >= count) {
        currentIndex = delta < 0 ? 0 : -1;
    }
    return ((currentIndex + delta) % count + count) % count;
}

function pointerMovedEnough(previous, current, threshold) {
    if (!previous || !current) {
        return false;
    }
    var dx = Number(current.x) - Number(previous.x);
    var dy = Number(current.y) - Number(previous.y);
    threshold = Math.max(0, Number(threshold) || 0);
    return isFinite(dx) && isFinite(dy) && Math.sqrt(dx * dx + dy * dy) >= threshold;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        filterApplications: filterApplications,
        moveSelection: moveSelection,
        pointerMovedEnough: pointerMovedEnough,
        prepareApplications: prepareApplications
    };
}
